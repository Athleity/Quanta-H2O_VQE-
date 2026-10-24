#!/usr/bin/env python3
"""Run one reproducible, staged H2O/PUCCSD optimizer study.

The driver (1) builds an empirical one-repetition PUCCSD reference with
multi-start SLSQP, (2) tunes SPSA on a separate fixed development seed set,
(3) freezes the selected SPSA schedule, and (4) compares SLSQP, COBYLA, and
the selected SPSA schedule on held-out paired starts. Every VQE run is
delegated to scripts/compat/h2o_vqe.py so its chemistry, mapping checks, energy verification,
and raw artifacts remain the single source of truth.

Run inside the activated project WSL environment. The default study is
deliberately substantial (roughly 2 hours on the runtime observed in the
initial pilot); budgets and seed counts can be changed on the command line.
Completed stages are safely reused when resuming the same configuration.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


BASE = Path(__file__).resolve().parents[1]
ENGINE = BASE / "scripts" / "compat" / "h2o_vqe.py"
DEFAULT_A_GRID = (0.001, 0.003, 0.01, 0.03)
DEFAULT_C_GRID = (0.01, 0.03, 0.1)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def command_signature(command: list[str]) -> list[str]:
    """Normalize host-specific interpreter and path prefixes for resumability."""
    normalized = list(command)
    if normalized:
        normalized[0] = "python"
    if len(normalized) > 1:
        normalized[1] = Path(normalized[1]).name
    if "--output" in normalized:
        index = normalized.index("--output") + 1
        if index < len(normalized):
            normalized[index] = "<run-output>"
    return normalized


def parse_grid(value: str, name: str) -> tuple[float, ...]:
    try:
        grid = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{name} must be comma-separated numbers") from exc
    if not grid or any(not math.isfinite(x) or x <= 0 for x in grid):
        raise argparse.ArgumentTypeError(f"{name} values must be finite and positive")
    if len(set(grid)) != len(grid):
        raise argparse.ArgumentTypeError(f"{name} values must be unique")
    return grid


def command_for(
    *,
    optimizer: str,
    output: Path,
    restarts: int,
    seed: int,
    budget: int,
    restart_scale: float,
    maxiter: int,
    a: float | None = None,
    c: float | None = None,
    random_only: bool = False,
) -> list[str]:
    command = [
        sys.executable,
        str(ENGINE),
        "--methods", "puccsd",
        "--optimizer", optimizer,
        "--ansatz-reps", "1",
        "--restarts", str(restarts),
        "--restart-scale", str(restart_scale),
        "--seed", str(seed),
        "--maxiter", str(maxiter),
        "--evaluation-budget", str(budget),
        "--output", str(output),
    ]
    if random_only:
        command.append("--random-restarts-only")
    if (a is None) != (c is None):
        raise ValueError("SPSA a and c must either both be set or both be omitted")
    if a is not None:
        command.extend((
            "--spsa-a", str(a),
            "--spsa-alpha", "0.602",
            "--spsa-c", str(c),
            "--spsa-gamma", "0.101",
        ))
    return command


def run_case(
    *,
    study_dir: Path,
    label: str,
    phase: str,
    command: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    output = Path(command[command.index("--output") + 1])
    manifest_path = output / "driver_manifest.json"
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "label": label,
        "phase": phase,
        "command": command,
        "command_signature": command_signature(command),
    }
    if manifest_path.exists():
        prior = read_json(manifest_path)
        prior_signature = prior.get("command_signature")
        if prior_signature is None and isinstance(prior.get("command"), list):
            prior_signature = command_signature(prior["command"])
        if (
            prior.get("label") != label
            or prior.get("phase") != phase
            or prior_signature != manifest["command_signature"]
        ):
            raise RuntimeError(
                f"Refusing to reuse {output}: its run manifest differs. "
                "Choose a fresh --output directory for changed settings."
            )
    else:
        write_json(manifest_path, manifest)

    summary_path = output / "summary.json"
    history_path = output / "optimization_history.csv"
    if summary_path.exists() and history_path.exists():
        print(f"[resume] {phase}/{label}: complete results already exist", flush=True)
    else:
        log_path = output / "driver.log"
        print(f"[run] {phase}/{label}", flush=True)
        started = time.monotonic()
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.run(
                command,
                cwd=BASE,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        elapsed = time.monotonic() - started
        if process.returncode != 0 or not summary_path.exists():
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
            raise RuntimeError(
                f"Run {phase}/{label} failed (exit {process.returncode}) after "
                f"{elapsed:.1f}s. Last log lines:\n{tail}"
            )
        print(f"[done] {phase}/{label}: {elapsed:.1f}s", flush=True)

    result = read_json(summary_path)
    rows = result.get("vqe_runs")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"No VQE run records found in {summary_path}")
    refs = result.get("reference", {})
    casci = refs.get("frozen_core_casci_hartree")
    if casci is None:
        raise ValueError(f"Missing CASCI reference in {summary_path}")
    # Fail closed if the execution environment used the old code which did not
    # put the optimizer's initial point into the best-so-far/evaluation budget.
    for row in rows:
        if row.get("optimizer") in {"spsa", "cobyla", "slsqp"}:
            if "initial_energy_hartree" not in row:
                raise RuntimeError(
                    f"{summary_path} lacks initial_energy_hartree. The WSL copy of "
                    "scripts/compat/h2o_vqe.py is stale; sync the updated engine before continuing."
                )
    with history_path.open(newline="", encoding="utf-8") as stream:
        history = list(csv.DictReader(stream))
    return result, history


def median_iqr(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "q1": None, "q3": None, "iqr": None}
    ordered = sorted(values)
    q1, q3 = statistics.quantiles(ordered, n=4, method="inclusive")[0::2] if len(ordered) > 1 else (ordered[0], ordered[0])
    med = statistics.median(ordered)
    return {"median": med, "q1": q1, "q3": q3, "iqr": q3 - q1}


def collect_run_rows(
    *,
    phase: str,
    label: str,
    result: dict[str, Any],
    ansatz_reference_hartree: float,
) -> list[dict[str, Any]]:
    casci = float(result["reference"]["frozen_core_casci_hartree"])
    rows: list[dict[str, Any]] = []
    for record in result["vqe_runs"]:
        energy = float(record["total_energy_hartree"])
        initial_total = record.get("initial_total_energy_hartree")
        if initial_total is None and record.get("initial_electronic_energy_hartree") is not None:
            # New schema: initial_energy_hartree already includes the offset.
            initial_total = record.get("initial_energy_hartree")
        elif initial_total is None and record.get("initial_energy_hartree") is not None:
            # Old schema: initial_energy_hartree held only the VQE objective.
            initial_total = (
                float(record["initial_energy_hartree"])
                + float(record["total_energy_offset_hartree"])
            )
        rows.append({
            "phase": phase,
            "label": label,
            "optimizer": record.get("optimizer"),
            "trial": record.get("trial"),
            "seed": record.get("seed"),
            "energy_hartree": energy,
            "error_vs_casci_mha": (energy - casci) * 1000.0,
            "gap_vs_reference_mha": (energy - ansatz_reference_hartree) * 1000.0,
            # Some completed runs predate the total-energy naming fix. The
            # VQE objective omits a constant offset, so reconstruct total
            # initial energy when aggregating those older raw summaries.
            "initial_energy_hartree": (
                None if initial_total is None else float(initial_total)
            ),
            "initial_electronic_energy_hartree": record.get(
                "initial_electronic_energy_hartree",
                record.get("initial_energy_hartree"),
            ),
            "objective_evaluations": record.get("budgeted_objective_evaluations"),
            "gradient_evaluations": record.get("budgeted_gradient_evaluations"),
            "final_gradient_norm": record.get("optimizer_final_gradient_norm"),
            "budget_reached": record.get("optimizer_budget_reached"),
            "elapsed_seconds": record.get("elapsed_seconds"),
            "parameters": record.get("num_parameters"),
            "cx_level3": record.get("ansatz_cx_count_optimization_level_3"),
        })
    return rows


def load_history(path: Path, phase: str, label: str) -> list[dict[str, Any]]:
    with (path / "optimization_history.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row["phase"] = phase
        row["label"] = label
        row["optimizer"] = (
            "spsa" if phase == "tuning" or label == "selected_spsa"
            else "slsqp" if label == "multistart_slsqp"
            else label
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_plots(study_dir: Path, history_rows: list[dict[str, Any]], casci: float) -> None:
    try:
        # Use a headless backend and a writable per-study cache so report
        # regeneration works both in WSL shells and locked-down Windows runs.
        os.environ.setdefault("MPLCONFIGDIR", str(study_dir / ".mplconfig"))
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib unavailable; skipping driver-level plots", file=sys.stderr)
        return

    # Plot tuning traces separately from the held-out comparison; a single
    # joined line would incorrectly imply that unrelated runs are continuous.
    fig, ax = plt.subplots(figsize=(10, 6), constrained_layout=True)
    grouped: dict[str, list[tuple[int, float]]] = {}
    for row in history_rows:
        if not row.get("energy_total_hartree"):
            continue
        key = f"{row['phase']} | {row['label']} | trial {row.get('trial', 0)}"
        grouped.setdefault(key, []).append((
            int(float(row.get("evaluation", 0))),
            (float(row["energy_total_hartree"]) - casci) * 1000.0,
        ))
    # Avoid turning a dense tuning grid into an unreadable plot. Keep only
    # final held-out traces plus the selected SPSA and reference runs.
    for label, points in grouped.items():
        if not (label.startswith("heldout") or "selected_spsa" in label or label.startswith("reference")):
            continue
        points.sort()
        ax.plot([p[0] for p in points], [p[1] for p in points], alpha=0.65, label=label)
    ax.axhline(0.0, color="black", linewidth=1, label="CASCI")
    ax.axhline(1.6, color="crimson", linestyle="--", linewidth=1, label="1.6 mHa chemical accuracy")
    ax.set_xlabel("Recorded objective evaluation")
    ax.set_ylabel("Energy above frozen-core CASCI (mHa)")
    ax.set_title("Asymmetric H₂O PUCCSD optimizer study (ideal statevector)")
    ax.grid(alpha=0.25)
    if grouped:
        ax.legend(fontsize=7, ncol=2)
    fig.savefig(study_dir / "heldout_convergence.png", dpi=180)
    plt.close(fig)

    held = [row for row in history_rows if row.get("phase") == "heldout"]
    checkpoints = (100, 200, 300, 500, 800, 1000)
    checkpoint_rows: list[dict[str, Any]] = []
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in held:
        key = (str(row.get("label")), str(row.get("trial", 0)), str(row.get("optimizer", "")))
        groups.setdefault(key, []).append(row)
    for (label, trial, optimizer), rows in groups.items():
        rows.sort(key=lambda r: int(float(r.get("evaluation", 0))))
        for checkpoint in checkpoints:
            eligible = [r for r in rows if int(float(r.get("evaluation", 0))) <= checkpoint]
            if eligible:
                last = eligible[-1]
                checkpoint_rows.append({
                    "label": label, "trial": trial, "optimizer": optimizer,
                    "checkpoint_evaluations": checkpoint,
                    "actual_evaluation": int(float(last["evaluation"])),
                    "gap_vs_casci_mha": (float(last["energy_total_hartree"]) - casci) * 1000.0,
                })
    write_csv(study_dir / "heldout_checkpoints.csv", checkpoint_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results/optimizers/systematic-optimizer-study")
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--restart-scale", type=float, default=0.5)
    parser.add_argument("--tune-restarts", type=int, default=4,
                        help="development starts, including the HF start (default 4)")
    parser.add_argument("--holdout-restarts", type=int, default=10,
                        help="held-out perturbed starts per optimizer (default 10)")
    parser.add_argument("--reference-restarts", type=int, default=10)
    parser.add_argument("--tune-budget", type=int, default=300,
                        help="objective calls per tuning start; 300=about 149 SPSA updates")
    parser.add_argument("--final-budget", type=int, default=500,
                        help="objective calls per held-out start")
    parser.add_argument("--reference-budget", type=int, default=1000)
    parser.add_argument("--reference-maxiter", type=int, default=500)
    parser.add_argument("--maxiter", type=int, default=10000)
    parser.add_argument("--a-grid", type=lambda x: parse_grid(x, "--a-grid"),
                        default=DEFAULT_A_GRID)
    parser.add_argument("--c-grid", type=lambda x: parse_grid(x, "--c-grid"),
                        default=DEFAULT_C_GRID)
    parser.add_argument("--no-auto-calibration", action="store_true",
                        help="omit Qiskit's automatic SPSA calibration candidate")
    args = parser.parse_args()

    if not ENGINE.is_file():
        parser.error(f"Could not find engine: {ENGINE}")
    for name in ("tune_restarts", "holdout_restarts", "reference_restarts",
                 "tune_budget", "final_budget", "reference_budget", "maxiter"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.tune_restarts < 2 or args.holdout_restarts < 2:
        parser.error("Use at least two development and held-out starts")
    if args.restart_scale <= 0 or not math.isfinite(args.restart_scale):
        parser.error("--restart-scale must be finite and positive")

    study_dir = Path(args.output).expanduser().resolve()
    study_dir.mkdir(parents=True, exist_ok=True)
    config = {
        # Keep the manifest portable between the WSL mount and Windows view.
        "engine": ENGINE.name, "geometry": {"fixed_oh_angstrom": 0.96,
                    "stretched_oh_angstrom": 2.20, "angle_deg": 104.5},
        "ansatz": "PUCCSD", "repetitions": 1,
        "seed": args.seed, "restart_scale": args.restart_scale,
        "tune_restarts": args.tune_restarts,
        "holdout_restarts": args.holdout_restarts,
        "reference_restarts": args.reference_restarts,
        "tune_budget": args.tune_budget, "final_budget": args.final_budget,
        "reference_budget": args.reference_budget,
        "reference_maxiter": args.reference_maxiter, "maxiter": args.maxiter,
        "a_grid": list(args.a_grid), "c_grid": list(args.c_grid),
        "include_auto_calibration": not args.no_auto_calibration,
        "spsa_alpha": 0.602, "spsa_gamma": 0.101,
        "selection_metric": "development median energy gap to multi-start SLSQP reference",
        "holdout_seed_offset": 800000,
        "reference_seed_offset": 400000,
    }
    config_path = study_dir / "study_config.json"
    if config_path.exists() and read_json(config_path) != config:
        parser.error("Output folder contains a different study config; choose a new --output")
    write_json(config_path, config)
    print(f"Study output: {study_dir}", flush=True)
    print("Stage 1/4: estimate the one-repetition PUCCSD reference with multi-start SLSQP", flush=True)

    all_results: list[dict[str, Any]] = []
    all_history: list[dict[str, Any]] = []
    reference_path = study_dir / "reference"
    reference_cmd = command_for(
        optimizer="slsqp", output=reference_path,
        restarts=args.reference_restarts, seed=args.seed + 400000,
        budget=args.reference_budget, restart_scale=args.restart_scale,
        maxiter=args.reference_maxiter,
    )
    ref_result, ref_history = run_case(
        study_dir=study_dir, label="multistart_slsqp", phase="reference", command=reference_cmd
    )
    reference_energy = min(float(row["total_energy_hartree"]) for row in ref_result["vqe_runs"])
    casci = float(ref_result["reference"]["frozen_core_casci_hartree"])
    all_results.extend(collect_run_rows(
        phase="reference", label="multistart_slsqp", result=ref_result,
        ansatz_reference_hartree=reference_energy,
    ))
    all_history.extend(load_history(reference_path, "reference", "multistart_slsqp"))
    print(f"Reference anchor: {reference_energy:.12f} Ha; CASCI: {casci:.12f} Ha", flush=True)

    schedules: list[tuple[str, float | None, float | None]] = []
    if not args.no_auto_calibration:
        schedules.append(("auto_calibration", None, None))
    schedules.extend(
        (f"a{a:g}_c{c:g}", a, c)
        for a in args.a_grid for c in args.c_grid
    )
    print(f"Stage 2/4: tune on {args.tune_restarts} development starts across "
          f"{len(schedules)} preregistered SPSA settings", flush=True)

    tuning_scores: list[dict[str, Any]] = []
    for label, a, c in schedules:
        folder = study_dir / "tuning" / label
        command = command_for(
            optimizer="spsa", output=folder,
            restarts=args.tune_restarts, seed=args.seed,
            budget=args.tune_budget, restart_scale=args.restart_scale,
            maxiter=args.maxiter, a=a, c=c,
        )
        result, history = run_case(
            study_dir=study_dir, label=label, phase="tuning", command=command
        )
        run_rows = collect_run_rows(
            phase="tuning", label=label, result=result,
            ansatz_reference_hartree=reference_energy,
        )
        all_results.extend(run_rows)
        all_history.extend(load_history(folder, "tuning", label))
        gaps = [row["gap_vs_reference_mha"] for row in run_rows]
        tuning_scores.append({
            "label": label, "a": a, "c": c, "n": len(gaps),
            **median_iqr([float(x) for x in gaps]),
            "median_casci_error_mha": statistics.median(
                float(row["error_vs_casci_mha"]) for row in run_rows
            ),
            "total_objective_evaluations": sum(
                int(row["objective_evaluations"] or 0) for row in run_rows
            ),
        })

    # Selection uses development data only. Ties are broken by smaller IQR,
    # then lower median CASCI error; held-out outcomes never choose the schedule.
    tuning_scores.sort(key=lambda row: (
        float(row["median"]), float(row["iqr"]),
        float(row["median_casci_error_mha"]), row["label"],
    ))
    if not tuning_scores:
        raise RuntimeError("No SPSA tuning configurations were evaluated")
    selected = tuning_scores[0]
    selected_setting = next(item for item in schedules if item[0] == selected["label"])
    selected_label, selected_a, selected_c = selected_setting
    write_csv(study_dir / "spsa_tuning_ranked.csv", tuning_scores)
    write_json(study_dir / "selected_spsa.json", {
        "selection_data": "development set only",
        "selected": selected,
        "a": selected_a, "alpha": 0.602,
        "c": selected_c, "gamma": 0.101,
    })
    print(f"Selected setting from development data: {selected_label}; "
          f"median reference gap={selected['median']:.3f} mHa", flush=True)

    print("Stage 3/4: frozen held-out comparison of SLSQP, COBYLA, selected SPSA", flush=True)
    heldout_seed = args.seed + 800000
    heldout_methods = (
        ("slsqp", "slsqp", None, None),
        ("lbfgsb", "lbfgsb", None, None),
        ("cobyla", "cobyla", None, None),
        ("powell", "powell", None, None),
        ("selected_spsa", "spsa", selected_a, selected_c),
    )
    for label, optimizer, a, c in heldout_methods:
        folder = study_dir / "heldout" / label
        command = command_for(
            optimizer=optimizer, output=folder,
            restarts=args.holdout_restarts, seed=heldout_seed,
            budget=args.final_budget, restart_scale=args.restart_scale,
            maxiter=args.maxiter, a=a, c=c, random_only=True,
        )
        result, _ = run_case(
            study_dir=study_dir, label=label, phase="heldout", command=command
        )
        all_results.extend(collect_run_rows(
            phase="heldout", label=label, result=result,
            ansatz_reference_hartree=reference_energy,
        ))
        all_history.extend(load_history(folder, "heldout", label))

    write_csv(study_dir / "all_run_metrics.csv", all_results)
    write_csv(study_dir / "all_convergence_history.csv", all_history)
    write_plots(study_dir, all_history, casci)

    heldout_summary: dict[str, Any] = {}
    heldout_by_label: dict[str, dict[int, dict[str, Any]]] = {}
    for label, _, _, _ in heldout_methods:
        rows = [row for row in all_results if row["phase"] == "heldout" and row["label"] == label]
        heldout_by_label[label] = {int(row["trial"]): row for row in rows}
        energy_errors = [float(row["error_vs_casci_mha"]) for row in rows]
        ref_gaps = [float(row["gap_vs_reference_mha"]) for row in rows]
        heldout_summary[label] = {
            "runs": len(rows),
            "error_vs_casci_mha": median_iqr(energy_errors),
            "gap_vs_reference_mha": median_iqr(ref_gaps),
            "chemical_accuracy_successes": sum(abs(x) <= 1.6 for x in energy_errors),
            "budget_exhaustions": sum(bool(row["budget_reached"]) for row in rows),
            "median_elapsed_seconds": statistics.median(
                float(row["elapsed_seconds"]) for row in rows if row["elapsed_seconds"] is not None
            ),
        }

    # Paired differences use identical seeded starting vectors across methods.
    # Negative means lower CASCI error than SLSQP for that same start.
    slsqp_trials = heldout_by_label["slsqp"]
    for label, values in heldout_summary.items():
        if label == "slsqp":
            continue
        shared_trials = sorted(set(slsqp_trials) & set(heldout_by_label[label]))
        paired = [
            float(heldout_by_label[label][trial]["error_vs_casci_mha"])
            - float(slsqp_trials[trial]["error_vs_casci_mha"])
            for trial in shared_trials
        ]
        values["paired_error_difference_vs_slsqp_mha"] = {
            **median_iqr(paired),
            "wins_lower_error": sum(value < 0 for value in paired),
            "ties": sum(value == 0 for value in paired),
            "paired_runs": len(paired),
        }

    best_observed = min(all_results, key=lambda row: float(row["energy_hartree"]))

    report = {
        "study_config": config,
        "casci_reference_hartree": casci,
        "estimated_ansatz_reference_hartree": reference_energy,
        "estimated_ansatz_reference_source": "minimum verified energy from multi-start, budgeted SLSQP search; not a global-optimum proof",
        "best_energy_observed_across_all_phases_hartree": best_observed["energy_hartree"],
        "best_energy_observed_source": {
            "phase": best_observed["phase"],
            "optimizer": best_observed["label"],
            "trial": best_observed["trial"],
            "error_vs_casci_mha": best_observed["error_vs_casci_mha"],
        },
        "selected_spsa_setting": read_json(study_dir / "selected_spsa.json"),
        "development_tuning_ranked": tuning_scores,
        "heldout_optimizer_summary": heldout_summary,
        "interpretation_limits": [
            "All objectives are ideal exact-statevector energies; no finite-shot or hardware-noise claim.",
            "The SLSQP multi-start minimum is an empirical ansatz reference, not a mathematical global-optimum certificate.",
            "SLSQP reverse-mode gradients are counted separately from objective calls; equal objective-call budgets do not imply equal classical wall-clock work.",
            "The tuning and held-out seed ranges are disjoint; held-out results do not select SPSA settings.",
        ],
    }
    write_json(study_dir / "study_report.json", report)
    (study_dir / "study_report.md").write_text(render_report(report), encoding="utf-8")
    print("Stage 4/4: reports written", flush=True)
    print(f"Study complete: {study_dir}", flush=True)
    print(f"Human-readable report: {study_dir / 'study_report.md'}", flush=True)
    return 0


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "# Systematic asymmetric-H₂O optimizer study", "",
        "## Reference", "",
        f"- Frozen-core CASCI: `{report['casci_reference_hartree']:.12f}` Ha.",
        f"- Empirical PUCCSD(1) reference: `{report['estimated_ansatz_reference_hartree']:.12f}` Ha.",
        "- This is a multi-start SLSQP reference, not a proof of the global ansatz minimum.", "",
        f"- Best energy observed across all phases: `{report['best_energy_observed_across_all_phases_hartree']:.12f}` Ha "
        f"({report['best_energy_observed_source']['error_vs_casci_mha']:.3f} mHa above CASCI; "
        f"{report['best_energy_observed_source']['optimizer']}, trial {report['best_energy_observed_source']['trial']}).",
        "- Negative gaps to the SLSQP anchor mean another method improved that empirical anchor slightly; they do not indicate an energy below CASCI.", "",
        "## SPSA setting selection", "",
        f"- Chosen on development runs only: `{report['selected_spsa_setting']['selected']['label']}`.",
        f"- Parameters: `a={report['selected_spsa_setting']['a']}`, `alpha=0.602`, "
        f"`c={report['selected_spsa_setting']['c']}`, `gamma=0.101`.",
        "- `auto_calibration` selects Qiskit's calibration procedure, which recalibrates from each run's initial point; it is not one numeric schedule frozen from tuning. The run records the procedure and seed, but not the calibrated generator values.",
        "- Full ranking: `spsa_tuning_ranked.csv`.", "",
        "## Held-out optimizer results", "",
        "| Optimizer | Runs | Median error vs CASCI (mHa) | IQR (mHa) | Median gap vs SLSQP anchor (mHa) | Paired median difference vs SLSQP (mHa) | Lower-error wins | Chemical-accuracy successes | Budget exhausted |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, values in report["heldout_optimizer_summary"].items():
        e = values["error_vs_casci_mha"]
        g = values["gap_vs_reference_mha"]
        paired = values.get("paired_error_difference_vs_slsqp_mha")
        paired_median = "—" if paired is None else f"{paired['median']:.3f}"
        paired_wins = "—" if paired is None else f"{paired['wins_lower_error']}/{paired['paired_runs']}"
        lines.append(
            f"| {name} | {values['runs']} | {e['median']:.3f} | {e['iqr']:.3f} "
            f"| {g['median']:.3f} | {paired_median} | {paired_wins} "
            f"| {values['chemical_accuracy_successes']}/{values['runs']} "
            f"| {values['budget_exhaustions']}/{values['runs']} |"
        )
    lines.extend(("", "## Files", "",
                  "- `all_run_metrics.csv`: one row per optimizer run.",
                  "- `all_convergence_history.csv`: raw recorded energy traces.",
                  "- `heldout_checkpoints.csv`: held-out energies at common evaluation checkpoints.",
                  "- `heldout_convergence.png`: held-out convergence plot.",
                  "- `study_report.json`: machine-readable complete summary.",
                  "- Each subrun directory retains its original `summary.json`, history, plot, and driver log.",
                  "", "## Interpretation limits", ""))
    lines.extend(f"- {item}" for item in report["interpretation_limits"])
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
