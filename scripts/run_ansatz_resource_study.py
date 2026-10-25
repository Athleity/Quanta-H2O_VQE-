#!/usr/bin/env python3
"""Compare H2O UCCSD/PUCCSD repetition counts at matched geometry and budgets.

Runs the maintained scripts/compat/h2o_vqe.py engine; each run retains its reference checks,
independent mapped-CASCI validation, histories, and transpilation metrics. The
driver does not claim that a finite multi-start search proves a global minimum.

Example (WSL, from this project directory):
    python scripts/run_ansatz_resource_study.py --output results/ansatz/ansatz-resource-study

Resume a partially completed study with the same options:
    python scripts/run_ansatz_resource_study.py --output results/ansatz/ansatz-resource-study --resume
"""

from __future__ import annotations
# INSTALL COMMAND (Quanta VQE)
# From the repository root, install dependencies with:
# python -m pip install --prefer-binary -r config/requirements/requirements-wsl.txt


import argparse
import csv
import json
import math
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "scripts" / "compat" / "h2o_vqe.py"
DEFAULT_CONFIGS = (("uccsd", 1), ("puccsd", 1), ("puccsd", 2), ("puccsd", 3))


def parse_configs(value: str) -> tuple[tuple[str, int], ...]:
    """Parse e.g. ``uccsd:1,puccsd:1,puccsd:2,puccsd:3``."""
    configs: list[tuple[str, int]] = []
    for item in value.split(","):
        parts = item.strip().lower().split(":")
        if len(parts) != 2 or parts[0] not in {"uccsd", "puccsd"}:
            raise argparse.ArgumentTypeError(
                "ansätze must be comma-separated uccsd:REPS or puccsd:REPS values"
            )
        try:
            reps = int(parts[1])
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid repetition count in {item!r}") from exc
        if reps < 1:
            raise argparse.ArgumentTypeError("repetition counts must be positive")
        config = (parts[0], reps)
        if config in configs:
            raise argparse.ArgumentTypeError(f"duplicate ansatz configuration: {item}")
        configs.append(config)
    if not configs:
        raise argparse.ArgumentTypeError("at least one ansatz configuration is required")
    return tuple(configs)


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_run(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    summary_file = run_dir / "summary.json"
    if not summary_file.is_file():
        raise FileNotFoundError(f"run is missing its summary: {summary_file}")
    document = json.loads(summary_file.read_text(encoding="utf-8"))
    reference = document.get("reference", {})
    runs = document.get("vqe_runs", [])
    if not runs:
        raise ValueError(f"run contains no VQE records: {summary_file}")
    return reference, document


def run_command(args: argparse.Namespace, method: str, reps: int, run_dir: Path) -> None:
    command = [
        sys.executable,
        str(ENGINE),
        "--methods", method,
        "--ansatz-reps", str(reps),
        "--optimizer", args.optimizer,
        "--restarts", str(args.restarts),
        "--restart-scale", str(args.restart_scale),
        "--seed", str(args.seed),
        "--maxiter", str(args.maxiter),
        "--evaluation-budget", str(args.evaluation_budget),
        "--fixed-oh", str(args.fixed_oh),
        "--stretched-oh", str(args.stretched_oh),
        "--angle", str(args.angle),
        "--output", str(run_dir),
    ]
    started = time.monotonic()
    log_path = run_dir.parent / f"{run_dir.name}.log"
    run_dir.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write("COMMAND: " + " ".join(command) + "\n\n")
        log.flush()
        result = subprocess.run(
            command,
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    elapsed = time.monotonic() - started
    if result.returncode:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-5000:]
        raise RuntimeError(
            f"{method} reps={reps} failed with exit code {result.returncode}; "
            f"last output from {log_path}:\n{tail}"
        )
    print(f"Completed {method} reps={reps} in {elapsed:.1f}s; log: {log_path}")


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def consolidate(args: argparse.Namespace, output: Path) -> None:
    rows: list[dict[str, Any]] = []
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for method, reps in args.configs:
        run_dir = output / f"{method}-reps{reps}"
        reference, doc = read_run(run_dir)
        casci = float(reference["frozen_core_casci_hartree"])
        for record in doc["vqe_runs"]:
            energy = float(record["total_energy_hartree"])
            row = {
                "method": method,
                "reps": reps,
                "trial": int(record["trial"]),
                "seed": int(record["seed"]),
                "energy_hartree": energy,
                "casci_hartree": casci,
                "absolute_error_mha": 1000.0 * abs(energy - casci),
                "chemical_accuracy": abs(energy - casci) <= 0.0016,
                "parameters": record.get("num_parameters"),
                "cx_level0": record.get("ansatz_cx_count"),
                "cx_level3": record.get("ansatz_cx_count_optimization_level_3"),
                "depth_level0": record.get("ansatz_depth"),
                "depth_level3": record.get("ansatz_depth_optimization_level_3"),
                "energy_calls": record.get("num_energy_evaluations"),
                "gradient_calls": record.get("budgeted_gradient_evaluations"),
                "optimizer_budget_reached": record.get("optimizer_budget_reached"),
                "termination": record.get("optimizer_termination_assessment"),
                "elapsed_seconds": record.get("elapsed_seconds"),
                "run_directory": str(run_dir),
            }
            rows.append(row)
            grouped.setdefault((method, reps), []).append(row)

    columns = list(rows[0]) if rows else []
    with (output / "ansatz_runs.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    aggregates: list[dict[str, Any]] = []
    for (method, reps), group in grouped.items():
        errors = [float(row["absolute_error_mha"]) for row in group]
        # Resource metrics are circuit properties and should be constant across
        # starts; assert that instead of silently averaging inconsistent data.
        for key in ("parameters", "cx_level0", "cx_level3", "depth_level0", "depth_level3"):
            values = {row[key] for row in group}
            if len(values) != 1:
                raise ValueError(f"{method} reps={reps} has inconsistent {key}: {values}")
        aggregates.append({
            "method": method,
            "reps": reps,
            "runs": len(group),
            "median_error_mha": statistics.median(errors),
            "q1_error_mha": percentile(errors, 0.25),
            "q3_error_mha": percentile(errors, 0.75),
            "best_error_mha": min(errors),
            "chemical_accuracy_successes": sum(bool(row["chemical_accuracy"]) for row in group),
            "median_energy_calls": statistics.median(float(row["energy_calls"]) for row in group),
            "median_elapsed_seconds": statistics.median(float(row["elapsed_seconds"]) for row in group),
            "parameters": group[0]["parameters"],
            "cx_level0": group[0]["cx_level0"],
            "cx_level3": group[0]["cx_level3"],
            "depth_level0": group[0]["depth_level0"],
            "depth_level3": group[0]["depth_level3"],
            "budget_exhausted_runs": sum(row["optimizer_budget_reached"] is True for row in group),
            # This is a transparent workload proxy, not a hardware shot count:
            # each objective evaluation executes a parameterized circuit, and
            # ansatz CX count approximates its two-qubit gate work.
            "median_cx_evaluation_proxy": (
                statistics.median(float(row["energy_calls"]) for row in group)
                * int(group[0]["cx_level3"])
            ),
        })
    summary = {
        "study": "H2O asymmetric stretch UCCSD/PUCCSD expressibility and resource comparison",
        "geometry_angstrom": {
            "fixed_oh": args.fixed_oh,
            "stretched_oh": args.stretched_oh,
            "hoh_angle_deg": args.angle,
        },
        "active_space": "CAS(8e,6o), frozen core, STO-3G",
        "optimizer": args.optimizer,
        "evaluation_budget_per_run": args.evaluation_budget,
        "restarts_per_configuration": args.restarts,
        "casci_is_ansatz_independent_global_reference": True,
        "limitations": [
            "Finite multi-start optimization does not prove a global ansatz minimum.",
            "Exact statevector objective; no finite-shot or hardware claim.",
            "Circuit counts are transpiler estimates, not hardware-routed counts.",
            "Different ansätze have different parameter spaces; same seed does not make their starts physically paired.",
        ],
        "aggregates": aggregates,
    }
    write_json(output / "ansatz_summary.json", summary)

    # Generate a static, presentation-ready Pareto plot. Error bars show the
    # interquartile range across independent starts, not a confidence interval.
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "matplotlib is required for the summary plot; install the project's "
            "config/requirements/requirements-wsl.txt and rerun with --resume"
        ) from exc
    fig, ax = plt.subplots(figsize=(8.4, 5.4), constrained_layout=True)
    colors = {"uccsd": "#2364AA", "puccsd": "#D1495B"}
    for item in aggregates:
        x = int(item["cx_level3"])
        median = float(item["median_error_mha"])
        low = median - float(item["q1_error_mha"])
        high = float(item["q3_error_mha"]) - median
        ax.errorbar(
            x, median, yerr=[[low], [high]], fmt="o", capsize=4,
            color=colors[item["method"]], markersize=7,
        )
        ax.annotate(
            f"{item['method'].upper()} ×{item['reps']}\n"
            f"{item['parameters']} params",
            (x, median), xytext=(7, 8), textcoords="offset points", fontsize=8,
        )
    ax.axhline(1.6, color="#B22222", linestyle="--", linewidth=1.2,
               label="1.6 mHa (active-space chemical-accuracy threshold)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Level-3 transpiled CX count per state preparation (log scale)")
    ax.set_ylabel("Absolute energy error vs CASCI (mHa; median, IQR)")
    ax.set_title("Asymmetric H₂O: accuracy versus ansatz resources")
    ax.grid(True, which="both", alpha=0.22)
    ax.legend(loc="best", fontsize=8)
    fig.savefig(output / "ansatz_accuracy_resource_pareto.png", dpi=220)
    plt.close(fig)

    report_lines = [
        "# H₂O ansatz and resource comparison",
        "",
        f"Geometry: fixed O–H = {args.fixed_oh:.4f} Å; stretched O–H = "
        f"{args.stretched_oh:.4f} Å; angle = {args.angle:.3f}°.",
        "Model: STO-3G, frozen-core CAS(8e,6o); exact statevector energies.",
        f"Optimizer: {args.optimizer}; call cap = {args.evaluation_budget}; "
        f"starts per configuration = {args.restarts}.",
        "",
        "Median errors are compared with each geometry's active-space CASCI. "
        "IQR describes the spread of runs; it is not a confidence interval.",
        "The CX-evaluation product is a circuit-work proxy only, not a measured "
        "hardware runtime or shot count.",
        "",
        "| Ansatz | Runs | Median error (mHa) | IQR (mHa) | Best (mHa) | "
        "Within 1.6 mHa | Parameters | CX, level 3 | Depth, level 3 | Budget-capped |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in aggregates:
        report_lines.append(
            f"| {item['method'].upper()} ×{item['reps']} | {item['runs']} | "
            f"{item['median_error_mha']:.3f} | "
            f"{item['q3_error_mha'] - item['q1_error_mha']:.3f} | "
            f"{item['best_error_mha']:.3f} | "
            f"{item['chemical_accuracy_successes']}/{item['runs']} | "
            f"{item['parameters']} | {item['cx_level3']} | {item['depth_level3']} | "
            f"{item['budget_exhausted_runs']}/{item['runs']} |"
        )
    report_lines.extend([
        "",
        "## Interpretation limits",
        "",
        "- Multi-start minima are empirical; they do not prove a global minimum.",
        "- A common objective-call cap does not equalize wall time or gradient cost.",
        "- Circuit counts are transpiler estimates, not device-routed metrics.",
        "- The chemical-accuracy threshold is relative to active-space CASCI; it does not remove STO-3G or active-space model error.",
        "- This is noiseless simulation. It does not establish finite-shot or hardware performance.",
        "- Repetition count changes both ansatz expressibility and circuit cost; that trade-off is the experiment.",
        "",
        "Plot: `ansatz_accuracy_resource_pareto.png`.",
    ])
    (output / "ansatz_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"Wrote {output / 'ansatz_runs.csv'}")
    print(f"Wrote {output / 'ansatz_summary.json'}")
    print(f"Wrote {output / 'ansatz_report.md'}")
    print(f"Wrote {output / 'ansatz_accuracy_resource_pareto.png'}")
    for item in aggregates:
        print(
            f"{item['method']:7s} reps={item['reps']} median |ΔCASCI|="
            f"{item['median_error_mha']:.3f} mHa; best={item['best_error_mha']:.3f} mHa; "
            f"params={item['parameters']}; CX(L3)={item['cx_level3']}; "
            f"chemical accuracy={item['chemical_accuracy_successes']}/{item['runs']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/ansatz/ansatz-resource-study"))
    parser.add_argument("--resume", action="store_true", help="reuse completed runs if study settings match")
    parser.add_argument("--configs", type=parse_configs, default=DEFAULT_CONFIGS)
    parser.add_argument("--optimizer", choices=("lbfgsb", "slsqp"), default="lbfgsb")
    parser.add_argument("--restarts", type=int, default=5, help="includes one zero-amplitude HF start")
    parser.add_argument("--restart-scale", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--maxiter", type=int, default=1000)
    parser.add_argument("--evaluation-budget", type=int, default=800)
    parser.add_argument("--fixed-oh", type=float, default=0.96)
    parser.add_argument("--stretched-oh", type=float, default=2.20)
    parser.add_argument("--angle", type=float, default=104.5)
    args = parser.parse_args()
    if args.restarts < 2:
        parser.error("--restarts must be at least 2 (HF plus at least one perturbed start)")
    if args.maxiter < 1 or args.evaluation_budget < 2 or args.restart_scale <= 0:
        parser.error("iteration/budget must be positive and restart scale must be > 0")

    output = args.output.expanduser().resolve()
    output_preexisted = output.exists()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "study_config.json"
    config = {
        "configs": [list(item) for item in args.configs],
        "optimizer": args.optimizer,
        "restarts": args.restarts,
        "restart_scale": args.restart_scale,
        "seed": args.seed,
        "maxiter": args.maxiter,
        "evaluation_budget": args.evaluation_budget,
        "fixed_oh": args.fixed_oh,
        "stretched_oh": args.stretched_oh,
        "angle": args.angle,
    }
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not args.resume:
            parser.error(f"{output} already has a study manifest; choose a new output or pass --resume")
        if old != config:
            parser.error("--resume settings differ from study_config.json; use a new output directory")
    else:
        if output_preexisted and any(output.iterdir()):
            parser.error(
                "output directory is nonempty but has no study_config.json; "
                "choose a new output directory"
            )
        write_json(manifest_path, config)

    for method, reps in args.configs:
        run_dir = output / f"{method}-reps{reps}"
        if (run_dir / "summary.json").is_file():
            if not args.resume:
                parser.error(f"{run_dir} already has results; use --resume or choose a new output")
            print(f"Reusing completed {method} reps={reps}")
            continue
        if run_dir.exists() and any(run_dir.iterdir()):
            parser.error(f"incomplete run directory exists: {run_dir}; inspect it before resuming")
        print(f"Running {method} reps={reps}")
        run_command(args, method, reps, run_dir)
    consolidate(args, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
