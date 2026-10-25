"""Backend-calibrated, finite-shot noise study for saved H2O VQE optima.

This is a local Aer simulation initialized from one IBM backend's current
calibration snapshot. It does not submit a QPU job. Aer's backend-derived
model is approximate: it captures calibrated gate, T1/T2, and readout errors,
but not every source of device behavior (for example, crosstalk and leakage).
"""

from __future__ import annotations
# INSTALL COMMAND (Quanta VQE)
# From the repository root, install dependencies with:
# python -m pip install --prefer-binary -r config/requirements/requirements-backend-noise.txt


import argparse
import csv
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .engine import Geometry, _require_scientific_stack, build_active_problem


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES = (
    ("uccsd_reps1", "results/ansatz/uccsd-slsqp100-updated", "uccsd"),
    ("puccsd_reps1", "results/ansatz/ansatz-resource-pilot/puccsd-reps1", "puccsd"),
    ("puccsd_reps2", "results/ansatz/puccsd-reps2-slsqp100", "puccsd"),
    ("puccsd_reps3", "results/optimizers/puccsd3-extra-slsqp-seed20261024", "puccsd"),
)


def _jsonable(value: Any) -> Any:
    """Convert SDK metadata to JSON-safe values without silently dropping it."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _atomic_json(path: Path, payload: Any) -> None:
    """Write a recoverable checkpoint without leaving a truncated JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_jsonable(payload), indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _write_group_csv(path: Path, seed_rows: list[dict[str, Any]]) -> None:
    """Persist all completed per-group estimates in a spreadsheet-friendly form."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    columns = (
        "seed",
        "group_index_1based",
        "group_energy_contribution_hartree",
        "group_standard_error_hartree",
        "shots_reported_by_primitive",
        "partial_hamiltonian_sum_hartree",
        "groups_completed",
        "groups_total",
        "is_full_energy_yet",
    )
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for seed_row in seed_rows:
            for group_row in seed_row.get("group_results", []):
                writer.writerow({"seed": seed_row["seed"], **group_row})
    os.replace(temporary, path)


def _read_case(run_dir: Path, method: str) -> tuple[dict[str, Any], dict[str, Any]]:
    summary_path = run_dir / "summary.json"
    reference_path = run_dir / "reference.json"
    for path in (summary_path, reference_path):
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"Required saved input is missing or empty: {path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    rows = [
        row for row in summary.get("vqe_runs", [])
        if row.get("method") == method and row.get("optimal_point") is not None
    ]
    if not rows:
        raise ValueError(
            f"No saved {method} optimum in {summary_path}. The saved run must include optimal_point."
        )
    # Select the lowest recorded energy. Keep the success/cap status in the
    # output so selecting an energy does not falsely imply convergence.
    return min(rows, key=lambda row: float(row["total_energy_hartree"])), reference


def _backend_calibration_snapshot(backend: Any) -> dict[str, Any]:
    props = backend.properties()
    if props is None:
        raise RuntimeError(
            f"Backend {backend.name} returned no calibration properties; cannot build a calibrated noise model."
        )
    snapshot: dict[str, Any] = {
        "backend": str(backend.name),
        "num_qubits": int(backend.num_qubits),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "last_update_date": _jsonable(getattr(props, "last_update_date", None)),
    }
    # Save the actual calibration data used by Aer so the run is auditable.
    if hasattr(props, "to_dict"):
        snapshot["properties"] = _jsonable(props.to_dict())
    return snapshot


def evaluate_case(
    *,
    label: str,
    run_dir: Path,
    method: str,
    physical_backend: Any,
    aer_backend: Any,
    shots_per_group: int,
    group_batch_size: int,
    seeds: list[int],
    optimization_level: int,
    progress_path: Path,
) -> dict[str, Any]:
    from qiskit.quantum_info import Statevector
    from qiskit.primitives import BackendEstimatorV2
    from qiskit.transpiler import generate_preset_pass_manager

    print(f"[{label}] loading saved {method} optimum from {run_dir}", flush=True)
    row, metadata = _read_case(run_dir, method)
    if "geometry" not in metadata or "references" not in metadata:
        raise ValueError(f"reference.json in {run_dir} lacks geometry/reference metadata")

    geometry = Geometry(**metadata["geometry"])
    active_problem, mapper, hamiltonian, _mapping = build_active_problem(
        geometry.pyscf_atom_spec()
    )
    stack = _require_scientific_stack()
    n_orbitals = int(active_problem.num_spatial_orbitals)
    particles = active_problem.num_particles
    hf_state = stack["HartreeFock"](n_orbitals, particles, mapper)
    ansatz_cls = {"uccsd": stack["UCCSD"], "puccsd": stack["PUCCSD"]}[method]
    circuit = ansatz_cls(
        n_orbitals,
        particles,
        mapper,
        reps=int(row.get("ansatz_reps", 1)),
        initial_state=hf_state,
    )
    point = np.asarray(row["optimal_point"], dtype=float)
    print(
        f"[{label}] rebuilt circuit: {n_orbitals} active orbitals, "
        f"{circuit.num_qubits} logical qubits, {circuit.num_parameters} parameters; "
        "checking saved ideal optimum",
        flush=True,
    )
    if point.shape != (circuit.num_parameters,):
        raise ValueError(
            f"Saved {method} parameter vector has {point.size} entries; "
            f"rebuilt circuit expects {circuit.num_parameters}."
        )

    # Validate that the saved parameters still reproduce the saved ideal
    # energy before comparing a noisy backend model. This catches parameter
    # ordering, geometry, mapper, and energy-offset mismatches early.
    bound_circuit = circuit.assign_parameters(
        dict(zip(circuit.parameters, point, strict=True)), inplace=False
    )
    ideal_electronic = float(
        np.real(Statevector.from_instruction(bound_circuit).expectation_value(hamiltonian))
    )
    offset = float(row["total_energy_offset_hartree"])
    rebuilt_ideal_total = ideal_electronic + offset
    saved_ideal_total = float(row["total_energy_hartree"])
    ideal_rebuild_delta = abs(rebuilt_ideal_total - saved_ideal_total)
    if ideal_rebuild_delta > 1e-7:
        raise ValueError(
            f"Saved optimum failed the noiseless reconstruction check for {label}: "
            f"rebuilt {rebuilt_ideal_total:.12f} Ha vs saved {saved_ideal_total:.12f} Ha "
            f"(difference {ideal_rebuild_delta:.3g} Ha). Refusing a mismatched noise comparison."
        )
    print(
        f"[{label}] saved optimum verified: ideal E={rebuilt_ideal_total:+.9f} Ha; "
        f"|ΔCASCI|={abs(rebuilt_ideal_total - float(metadata['references']['frozen_core_casci_hartree'])) * 1000:.3f} mHa; "
        f"starting backend transpilation (this precedes noisy sampling)",
        flush=True,
    )

    # Compile to the same target/topology whose calibration generated the Aer
    # noise model. Layout must also be applied to the Hamiltonian.
    pass_manager = generate_preset_pass_manager(
        backend=physical_backend,
        optimization_level=optimization_level,
        # Scheduling inserts target-timed delays so Aer can model idle-qubit
        # T1/T2 relaxation as well as relaxation during gates.
        scheduling_method="alap",
        seed_transpiler=20261024,
    )
    isa_circuit = pass_manager.run(circuit)
    if isa_circuit.layout is None:
        raise RuntimeError(
            "Backend transpilation did not return a layout; refusing to measure an operator "
            "whose physical-qubit mapping cannot be verified."
        )
    print(
        f"[{label}] backend circuit ready: depth={isa_circuit.depth()}, "
        f"physical qubits={isa_circuit.num_qubits}; building QWC measurement groups",
        flush=True,
    )

    # Explicitly partition the Hamiltonian into QWC groups. This lets the local
    # simulator checkpoint partial contributions instead of hiding all progress
    # inside one long Estimator call. These partial sums are diagnostics only;
    # they are not full-energy estimates until every group has completed.
    qwc_groups = hamiltonian.group_commuting(qubit_wise=True)
    groups = len(qwc_groups)
    if groups < 1:
        raise RuntimeError("Hamiltonian produced no qubit-wise commuting measurement groups")
    print(
        f"[{label}] measurement plan ready: {groups} QWC groups; "
        f"partial group sums will appear as each batch completes",
        flush=True,
    )

    # BackendEstimatorV2 accepts target precision, not a hard shot count.
    # Its implementation scales shots as O(precision^-2); therefore this is a
    # nominal per-group shot budget, and the actual count is recorded only when
    # the primitive exposes it in result metadata. It is not a total-energy
    # precision: total uncertainty is propagated from group standard errors.
    group_precision = 1.0 / math.sqrt(shots_per_group)
    isa_groups = [group.apply_layout(isa_circuit.layout) for group in qwc_groups]
    estimates: list[dict[str, Any]] = []
    for seed_index, seed in enumerate(seeds, start=1):
        seed_started = time.perf_counter()
        group_rows: list[dict[str, Any]] = []
        partial_sum = 0.0
        variance_sum = 0.0
        print(
            f"[{label}] seed {seed_index}/{len(seeds)}={seed}: "
            f"{groups} QWC groups; {shots_per_group} shots/group; "
            f"{math.ceil(groups / group_batch_size)} batches; "
            f"nominal total shot-equivalent={groups * shots_per_group:,}",
            flush=True,
        )
        for batch_index, batch_start in enumerate(range(0, groups, group_batch_size)):
            batch_stop = min(batch_start + group_batch_size, groups)
            batch_seed = (int(seed) * 1_000_003 + batch_index) % (2**32 - 1)
            print(
                f"[{label}] seed {seed_index}/{len(seeds)}: "
                f"running groups {batch_start + 1}-{batch_stop}/{groups}; "
                f"simulator seed={batch_seed}",
                flush=True,
            )
            estimator = BackendEstimatorV2(
                backend=aer_backend,
                options={
                    "abelian_grouping": True,
                    "seed_simulator": int(batch_seed),
                },
            )
            pubs = [
                (isa_circuit, isa_groups[index], point)
                for index in range(batch_start, batch_stop)
            ]
            job = estimator.run(pubs, precision=group_precision)
            last_status_print = time.perf_counter()
            while not job.done():
                time.sleep(5)
                now = time.perf_counter()
                if now - last_status_print >= 30:
                    try:
                        job_status = str(job.status())
                    except Exception:
                        job_status = "running"
                    print(
                        f"[{label}] seed {seed_index}/{len(seeds)}: "
                        f"batch groups {batch_start + 1}-{batch_stop}/{groups} "
                        f"still running; status={job_status}; "
                        f"elapsed={now - seed_started:.0f}s",
                        flush=True,
                    )
                    last_status_print = now

            batch_result = job.result()
            for offset_in_batch, pub in enumerate(batch_result):
                group_index = batch_start + offset_in_batch
                group_energy = float(np.real(np.asarray(pub.data.evs).item()))
                group_std = float(np.real(np.asarray(pub.data.stds).item()))
                partial_sum += group_energy
                variance_sum += group_std * group_std
                row_data = {
                    "group_index_1based": group_index + 1,
                    "group_energy_contribution_hartree": group_energy,
                    "group_standard_error_hartree": group_std,
                    "shots_reported_by_primitive": (
                        int(pub.metadata["shots"])
                        if isinstance(pub.metadata.get("shots"), (int, np.integer))
                        else None
                    ),
                    "primitive_metadata": _jsonable(pub.metadata),
                    "partial_hamiltonian_sum_hartree": partial_sum,
                    "groups_completed": group_index + 1,
                    "groups_total": groups,
                    "is_full_energy_yet": group_index + 1 == groups,
                }
                group_rows.append(row_data)
                # Print each group after its batch finishes. The cumulative
                # sum is explicitly labeled partial until the final group.
                label_text = "FULL electronic estimate" if group_index + 1 == groups else "partial sum"
                print(
                    f"[{label}] seed={seed} group {group_index + 1}/{groups}: "
                    f"contribution={group_energy:+.8f} Ha; "
                    f"{label_text}={partial_sum:+.8f} Ha",
                    flush=True,
                )

            # Checkpoint immediately after each completed batch, so an
            # interruption preserves every finished group estimate.
            seed_progress = {
                "label": label,
                "seed": int(seed),
                "status": "running" if batch_stop < groups else "seed_complete",
                "nominal_shot_equivalent_per_group": shots_per_group,
                "group_precision_proxy": group_precision,
                "groups_completed": len(group_rows),
                "groups_total": groups,
                "partial_hamiltonian_sum_hartree": partial_sum,
                "partial_sum_is_full_energy": len(group_rows) == groups,
                "completed_seed_estimates": estimates,
                "group_results": group_rows,
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            _atomic_json(progress_path, seed_progress)
            _write_group_csv(progress_path.with_suffix(".csv"), estimates + [seed_progress])

        electronic_energy = partial_sum
        statistical_std = math.sqrt(variance_sum)
        reported_shot_counts = [
            item["shots_reported_by_primitive"]
            for item in group_rows
            if item["shots_reported_by_primitive"] is not None
        ]
        shots_reported = (
            sum(reported_shot_counts)
            if len(reported_shot_counts) == len(group_rows)
            else None
        )
        estimates.append(
            {
                "seed": int(seed),
                "total_energy_hartree": electronic_energy + offset,
                "electronic_energy_hartree": electronic_energy,
                "primitive_reported_std_hartree": statistical_std,
                "nominal_shot_equivalent_per_group": shots_per_group,
                "nominal_total_shot_equivalent": groups * shots_per_group,
                "total_shots_reported_by_primitive": shots_reported,
                "measurement_group_count": groups,
                "group_results": group_rows,
            }
        )
        print(
            f"[{label}] seed {seed_index}/{len(seeds)} complete: "
            f"total E={electronic_energy + offset:+.9f} Ha, "
            f"reported σ={statistical_std:.3g} Ha, "
            f"elapsed={time.perf_counter() - seed_started:.1f}s",
            flush=True,
        )
        _atomic_json(
            progress_path,
            {
                "label": label,
                "status": "all_seeds_complete" if seed_index == len(seeds) else "seed_complete",
                "completed_seed_estimates": estimates,
                "current_seed": int(seed),
                "current_seed_total_energy_hartree": electronic_energy + offset,
                "current_seed_standard_error_hartree": statistical_std,
                "groups_total": groups,
                "nominal_shot_equivalent_per_group": shots_per_group,
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
        _write_group_csv(progress_path.with_suffix(".csv"), estimates)

    energies = np.asarray([item["total_energy_hartree"] for item in estimates])
    reported_stds = np.asarray(
        [item["primitive_reported_std_hartree"] for item in estimates], dtype=float
    )
    ideal_total = float(row["total_energy_hartree"])
    casci = float(metadata["references"]["frozen_core_casci_hartree"])
    operation_counts = {str(k): int(v) for k, v in isa_circuit.count_ops().items()}
    target = getattr(physical_backend, "target", None)
    two_qubit_names: set[str] = set()
    if target is not None:
        for name in target.operation_names:
            try:
                operation = target.operation_from_name(name)
                if getattr(operation, "num_qubits", None) == 2:
                    two_qubit_names.add(str(name))
            except (AttributeError, KeyError, TypeError):
                continue
    two_qubit_count = sum(
        count for name, count in operation_counts.items() if name in two_qubit_names
    )

    return {
        "label": label,
        "method": method,
        "ansatz_reps": int(row.get("ansatz_reps", 1)),
        "optimizer": row.get("optimizer"),
        "optimizer_success": row.get("optimizer_success"),
        "optimizer_message": row.get("optimizer_message"),
        "saved_ideal_energy_hartree": float(row["total_energy_hartree"]),
        "rebuilt_ideal_energy_hartree": rebuilt_ideal_total,
        "ideal_reconstruction_abs_difference_hartree": ideal_rebuild_delta,
        "saved_ideal_abs_error_vs_casci_hartree": abs(
            float(row["total_energy_hartree"]) - casci
        ),
        "active_casci_reference_hartree": casci,
        "backend_compiled_qubits": int(isa_circuit.num_qubits),
        "backend_compiled_depth": int(isa_circuit.depth()),
        "backend_native_two_qubit_gate_names": sorted(two_qubit_names),
        "backend_native_two_qubit_gate_count": int(two_qubit_count),
        "operation_counts": operation_counts,
        "qubit_wise_commuting_group_count": groups,
        "nominal_shot_equivalent_per_group": shots_per_group,
        "nominal_total_shot_equivalent_per_seed": groups * shots_per_group,
        "total_shots_reported_by_primitive_by_seed": [
            item["total_shots_reported_by_primitive"] for item in estimates
        ],
        "measurement_execution": (
            "Qubit-wise commuting groups measured in batches. Each group is a separate "
            "Estimator PUB with a target-precision-derived nominal shot equivalent; partial sums are not full "
            "energy estimates until all groups finish."
        ),
        "estimates_by_seed": estimates,
        "noisy_mean_energy_hartree": float(np.mean(energies)),
        "noisy_mean_signed_bias_vs_ideal_hartree": float(np.mean(energies) - ideal_total),
        "noisy_mean_abs_bias_vs_ideal_hartree": abs(float(np.mean(energies) - ideal_total)),
        "noisy_std_across_seeds_hartree": (
            float(np.std(energies, ddof=1)) if len(energies) > 1 else None
        ),
        "standard_error_of_seed_mean_hartree": float(
            np.sqrt(np.sum(reported_stds**2)) / len(reported_stds)
        ),
        "noisy_mean_abs_error_vs_casci_hartree": abs(float(np.mean(energies)) - casci),
        "noisy_estimate_is_guaranteed_to_respect_variational_bound": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    backend_source = parser.add_mutually_exclusive_group(required=True)
    backend_source.add_argument(
        "--backend", help="Exact live IBM backend name (reads calibration only; submits no QPU job)"
    )
    backend_source.add_argument(
        "--fake-backend",
        help="IBM fake-provider snapshot name, e.g. fake_brisbane (no credentials/network required)",
    )
    parser.add_argument("--shots-per-group", type=int, default=1024,
                        help="Nominal shot-equivalent budget per QWC group; EstimatorV2 uses precision scaling, so actual counts may differ")
    parser.add_argument("--group-batch-size", type=int, default=12,
                        help="Number of QWC groups submitted per local batch; controls progress frequency")
    parser.add_argument("--seeds", default="11,29,47", help="Comma-separated independent simulator seeds")
    parser.add_argument("--optimization-level", type=int, choices=range(4), default=1)
    parser.add_argument("--output", type=Path, default=Path("results/backend-noise-study"))
    parser.add_argument("--cases", default="puccsd_reps1,puccsd_reps3",
                        help="Comma-separated cases: uccsd_reps1,puccsd_reps1,puccsd_reps2,puccsd_reps3")
    args = parser.parse_args()
    if args.shots_per_group < 1:
        parser.error("--shots-per-group must be a positive integer")
    if args.group_batch_size < 1:
        parser.error("--group-batch-size must be a positive integer")
    try:
        seeds = [int(v.strip()) for v in args.seeds.split(",") if v.strip()]
    except ValueError:
        parser.error("--seeds must be comma-separated integers")
    if not seeds or len(set(seeds)) != len(seeds):
        parser.error("--seeds must be nonempty and unique")

    requested = [v.strip() for v in args.cases.split(",") if v.strip()]
    case_map = {label: (Path(path), method) for label, path, method in CASES}
    if not requested or len(set(requested)) != len(requested) or set(requested) - set(case_map):
        parser.error(f"--cases must be a unique subset of: {', '.join(case_map)}")

    try:
        from qiskit_aer import AerSimulator
        from qiskit_ibm_runtime import QiskitRuntimeService
    except ImportError as exc:
        print(
            "Backend-calibrated noise needs the optional dependencies. From the project root run:\n"
            "  python -m pip install --prefer-binary -r config/requirements/requirements-backend-noise.txt",
            file=sys.stderr,
        )
        print(f"Import detail: {exc}", file=sys.stderr)
        return 2

    try:
        if args.backend:
            service = QiskitRuntimeService()
            backend = service.backend(args.backend)
            calibration_source = "live IBM backend calibration snapshot"
        else:
            # Fake backends package historical calibration snapshots and are
            # useful for reproducible local noise studies when live credentials
            # or a teammate's backend access are unavailable. They are not
            # current-device calibrations and must be reported as snapshots.
            from qiskit_ibm_runtime.fake_provider import FakeProviderForBackendV2

            backend = FakeProviderForBackendV2().backend(name=args.fake_backend)
            calibration_source = "IBM fake-provider historical calibration snapshot"
        calibration = _backend_calibration_snapshot(backend)
        # Aer uses the backend's basis, topology, per-gate errors, T1/T2 and
        # readout properties. MPS avoids allocating a dense 2^N statevector
        # when the physical backend has many idle qubits after placement.
        aer_backend = AerSimulator.from_backend(backend, method="matrix_product_state")

        safe_backend = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(backend.name))
        output_dir = args.output / safe_backend
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "backend_noise_study.json"
        records = []
        payload = {
            "study_status": "running",
            "completed_cases": [],
            "requested_cases": requested,
            "model": "AerSimulator.from_backend using a captured IBM backend calibration snapshot",
            "calibration_source": calibration_source,
            "local_simulation_only": True,
            "qpu_jobs_submitted": 0,
            "important_limitations": [
                "Aer backend-derived noise is approximate, not a full digital twin.",
                "It does not generally capture crosstalk, leakage, drift, or all coherent/context-dependent errors.",
                "A noisy energy below the CASCI reference is not evidence of better accuracy; noise breaks the variational bound.",
            ],
            "backend_calibration": calibration,
            "noise_simulator": {
                "class": "qiskit_aer.AerSimulator.from_backend",
                "method": "matrix_product_state",
                "nominal_shot_equivalent_per_group": args.shots_per_group,
                "group_batch_size": args.group_batch_size,
                "seeds": seeds,
                "transpiler_optimization_level": args.optimization_level,
                "scheduling_method": "alap",
            },
            "cases": records,
        }
        # Persist calibration and progress before expensive simulation begins,
        # then atomically checkpoint after every completed ansatz case.
        _atomic_json(target, payload)
        for label in requested:
            run_dir, method = case_map[label]
            resolved = (PROJECT_ROOT / run_dir).resolve()
            print(
                f"[{label}] backend-calibrated Aer; backend={backend.name}; "
                f"shots/group={args.shots_per_group}; "
                f"batch_groups={args.group_batch_size}; seeds={seeds}",
                flush=True,
            )
            record = evaluate_case(
                label=label,
                run_dir=resolved,
                method=method,
                physical_backend=backend,
                aer_backend=aer_backend,
                shots_per_group=args.shots_per_group,
                group_batch_size=args.group_batch_size,
                seeds=seeds,
                optimization_level=args.optimization_level,
                progress_path=output_dir / f"{label}_progress.json",
            )
            records.append(record)
            payload["completed_cases"] = [item["label"] for item in records]
            payload["cases"] = records
            if len(records) == len(requested):
                payload["study_status"] = "complete"
            _atomic_json(target, payload)
            print(
                f"[{label}] noisy mean={record['noisy_mean_energy_hartree']:.9f} Ha; "
                f"|ΔCASCI|={record['noisy_mean_abs_error_vs_casci_hartree'] * 1000:.3f} mHa; "
                f"compiled 2q gates={record['backend_native_two_qubit_gate_count']}; "
                f"depth={record['backend_compiled_depth']}",
                flush=True,
            )

        print(f"Saved calibration snapshot and results: {target}")
        report_path = output_dir / "noise_report.md"
        report_lines = [
            "# Backend-calibrated H₂O noise study",
            "",
            f"- Backend snapshot: `{backend.name}`",
            f"- Calibration captured (UTC): `{calibration['captured_at_utc']}`",
            f"- Calibration last updated: `{calibration.get('last_update_date')}`",
            f"- Noise model: Aer from backend properties; local simulation only.",
            f"- Nominal shot-equivalent budget per QWC group: `{args.shots_per_group}`; seeds: `{', '.join(map(str, seeds))}`.",
            "",
            "| Ansatz | Reps | Ideal E (Ha) | Noisy mean E ± propagated shot SE (Ha) | Noise bias vs ideal (mHa) | |ΔCASCI| (mHa) | Native 2q gates | Depth |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for item in records:
            report_lines.append(
                "| {method} | {reps} | {ideal:.9f} | {mean:.9f} ± {se:.6f} | "
                "{bias:+.2f} | {delta:.2f} | {gates} | {depth} |".format(
                    method=item["method"],
                    reps=item["ansatz_reps"],
                    ideal=item["saved_ideal_energy_hartree"],
                    mean=item["noisy_mean_energy_hartree"],
                    se=item["standard_error_of_seed_mean_hartree"],
                    bias=1000 * item["noisy_mean_signed_bias_vs_ideal_hartree"],
                    delta=1000 * item["noisy_mean_abs_error_vs_casci_hartree"],
                    gates=item["backend_native_two_qubit_gate_count"],
                    depth=item["backend_compiled_depth"],
                )
            )
        report_lines.extend(
            [
                "",
                "## Interpretation limits",
                "",
                "This is a backend-calibrated Aer simulation from a captured backend snapshot, not a QPU result. "
                "The reported noisy energy is not guaranteed to obey the variational bound. "
                "Group-by-group partial sums are diagnostic only; only the completed all-group sum is a Hamiltonian energy estimate. "
                "The propagated shot standard error excludes calibration uncertainty and noise-model mismatch. EstimatorV2 precision implies an asymptotic shot budget, not an exact fixed count; actual counts are reported only when present in primitive metadata.",
                "",
                "Machine-readable results and calibration data are in `backend_noise_study.json`; "
                "checkpointed group contributions are in the corresponding `*_progress.json` and CSV files.",
            ]
        )
        report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        print(f"Saved presentation summary: {report_path}")
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
