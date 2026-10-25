"""Evaluate one saved H2O VQE optimum on a real IBM QPU.

This is a fixed-parameter energy measurement, not VQE optimization. It is
deliberately dry-run-only unless the caller passes --submit. Local compilation
and a noiseless reconstruction check happen before any Runtime job is sent.
"""

from __future__ import annotations
# INSTALL COMMAND (Quanta VQE)
# From the repository root, install dependencies with:
# python -m pip install --prefer-binary -r config/requirements/requirements-backend-noise.txt


import argparse
import getpass
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .engine import Geometry, _require_scientific_stack, build_active_problem


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _load_saved_optimum(run_dir: Path, requested_method: str | None, trial: int | None):
    summary_path = run_dir / "summary.json"
    reference_path = run_dir / "reference.json"
    for path in (summary_path, reference_path):
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(
                f"Missing saved VQE result {path}. Wait for the optimizer run to finish "
                "so it writes summary.json; a printed energy alone does not contain the angles."
            )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    rows = [
        row for row in summary.get("vqe_runs", [])
        if row.get("optimal_point") is not None
        and (requested_method is None or row.get("method") == requested_method)
        and (trial is None or int(row.get("trial", -1)) == trial)
    ]
    if not rows:
        raise ValueError(
            f"No saved optimum matched method={requested_method!r}, trial={trial!r} in {summary_path}."
        )
    row = min(rows, key=lambda item: float(item["total_energy_hartree"]))
    method = str(row.get("method", ""))
    if method not in {"uccsd", "puccsd"}:
        raise ValueError(f"Unsupported saved ansatz {method!r}; expected uccsd or puccsd.")
    if "geometry" not in reference or "references" not in reference:
        raise ValueError(f"Incomplete reference metadata: {reference_path}")
    return row, reference, method


def _runtime_estimator_class():
    """Prefer the current client-side IBM Runtime Estimator API."""
    try:
        from qiskit_ibm_runtime.executor_estimator import Estimator

        return Estimator, "qiskit_ibm_runtime.executor_estimator.Estimator"
    except ImportError:
        # Compatibility with earlier Runtime releases. The project backend-noise
        # extra currently pins >=0.50, where the client-side class is available.
        from qiskit_ibm_runtime import EstimatorV2

        return EstimatorV2, "qiskit_ibm_runtime.EstimatorV2 compatibility API"


def _native_two_qubit_count(circuit: Any, backend: Any) -> tuple[int, dict[str, int]]:
    counts = {str(name): int(count) for name, count in circuit.count_ops().items()}
    two_qubit_names: set[str] = set()
    for name in backend.target.operation_names:
        try:
            operation = backend.target.operation_from_name(name)
            if getattr(operation, "num_qubits", None) == 2:
                two_qubit_names.add(str(name))
        except (AttributeError, KeyError, TypeError):
            continue
    total = sum(count for name, count in counts.items() if name in two_qubit_names)
    return int(total), counts


def _progress(message: str) -> None:
    print(f"[{datetime.now().astimezone().strftime('%H:%M:%S')}] {message}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir", type=Path, required=True,
        help="Completed VQE output directory containing summary.json and reference.json.",
    )
    parser.add_argument("--backend", required=True, help="Exact IBM backend name, e.g. ibm_kingston.")
    parser.add_argument(
        "--instance",
        default=os.environ.get("IBM_QUANTUM_INSTANCE") or os.environ.get("IBM_QUANTUM_CRN"),
        help="IBM service instance CRN (or set IBM_QUANTUM_INSTANCE). Required to target the hackathon allocation.",
    )
    parser.add_argument("--method", choices=("uccsd", "puccsd"), default=None)
    parser.add_argument("--trial", type=int, default=None,
                        help="Use this saved trial index; default selects the lowest ideal energy in the run.")
    sampling = parser.add_mutually_exclusive_group()
    sampling.add_argument(
        "--shots", type=int, default=None,
        help="Explicit shots per measurement configuration; default 64 for a bounded pilot.",
    )
    sampling.add_argument(
        "--precision", type=float, default=None,
        help="Alternative Estimator target precision in Ha; actual shot usage is variable.",
    )
    parser.add_argument("--resilience-level", type=int, choices=(0, 1), default=1,
                        help="0=raw estimate; 1=IBM readout mitigation (TREX), with modest overhead.")
    parser.add_argument("--optimization-level", type=int, choices=range(4), default=3)
    parser.add_argument("--seed-transpiler", type=int, default=20261024)
    parser.add_argument("--max-execution-time", type=int, default=480,
                        help="QPU execution-time ceiling in seconds; default leaves margin in a 10-minute allocation.")
    parser.add_argument("--output", type=Path, default=Path("results/hardware"))
    parser.add_argument(
        "--submit", action="store_true",
        help="Actually submit one fixed-parameter energy job to the IBM QPU. Without this, only a Runtime dry run is requested.",
    )
    args = parser.parse_args(argv)
    if args.shots is None and args.precision is None:
        args.shots = 64
    if args.precision is not None and (
        not np.isfinite(args.precision) or args.precision <= 0
    ):
        parser.error("--precision must be a finite positive number")
    if args.shots is not None and args.shots < 8:
        parser.error("--shots must be at least 8 for the finite-shot QPU run")
    if not args.instance:
        parser.error("--instance is required; copy the hackathon instance CRN from IBM Quantum Platform")
    if args.max_execution_time < 1:
        parser.error("--max-execution-time must be positive")

    try:
        from qiskit.quantum_info import Statevector
        from qiskit.transpiler import generate_preset_pass_manager
        from qiskit_ibm_runtime import QiskitRuntimeService

        row, reference, method = _load_saved_optimum(args.run_dir, args.method, args.trial)
        geometry = Geometry(**reference["geometry"])
        problem, mapper, hamiltonian, mapping = build_active_problem(geometry.pyscf_atom_spec())
        stack = _require_scientific_stack()
        hartree_fock = stack["HartreeFock"](problem.num_spatial_orbitals, problem.num_particles, mapper)
        ansatz_class = {"uccsd": stack["UCCSD"], "puccsd": stack["PUCCSD"]}[method]
        circuit = ansatz_class(
            problem.num_spatial_orbitals,
            problem.num_particles,
            mapper,
            reps=int(row.get("ansatz_reps", 1)),
            initial_state=hartree_fock,
        )
        point = np.asarray(row["optimal_point"], dtype=float)
        if point.shape != (circuit.num_parameters,):
            raise ValueError(
                f"Saved parameter vector has {point.size} values; rebuilt circuit expects {circuit.num_parameters}."
            )
        bound_circuit = circuit.assign_parameters(
            dict(zip(circuit.parameters, point, strict=True)), inplace=False
        )

        # Fail closed if the stored angles, geometry, mapping, or software-built
        # ansatz no longer reproduce the saved ideal result.
        ideal_electronic = float(np.real(Statevector.from_instruction(bound_circuit).expectation_value(hamiltonian)))
        offset = float(row["total_energy_offset_hartree"])
        ideal_total = ideal_electronic + offset
        saved_total = float(row["total_energy_hartree"])
        ideal_delta = abs(ideal_total - saved_total)
        if ideal_delta > 1e-7:
            raise ValueError(
                f"Noiseless reconstruction mismatch ({ideal_delta:.3g} Ha): rebuilt {ideal_total:.12f}, "
                f"saved {saved_total:.12f}. Refusing QPU submission."
            )

        # Never accept or persist the API key in source code or command history.
        # Prefer an environment variable; otherwise prompt with terminal echo off.
        api_token = os.environ.get("IBM_QUANTUM_TOKEN")
        if not api_token:
            api_token = getpass.getpass("IBM Quantum API key (input is hidden): ").strip()
        if not api_token:
            raise ValueError("No IBM Quantum API key was provided")
        try:
            service = QiskitRuntimeService(
                channel="ibm_quantum_platform",
                token=api_token,
                instance=args.instance,
            )
        except Exception as auth_exc:
            detail = str(auth_exc)
            if api_token:
                detail = detail.replace(api_token, "<redacted>")
            raise RuntimeError(
                f"IBM authentication or instance selection failed: {type(auth_exc).__name__}: {detail[:400]}"
            ) from None
        finally:
            # The process does not need to retain the secret after constructing the service.
            api_token = ""
        backend = (
            service.backend(args.backend)
        )
        status = backend.status()
        if not bool(getattr(status, "operational", False)):
            raise RuntimeError(f"IBM backend {args.backend} is not operational (status={status}).")
        if bool(getattr(backend, "simulator", False)):
            raise RuntimeError(f"{args.backend} is a simulator, not a physical QPU.")

        _progress(f"Connected to {backend.name}; compiling fixed {method.upper()} reps={row.get('ansatz_reps')} circuit")
        pass_manager = generate_preset_pass_manager(
            backend=backend,
            optimization_level=args.optimization_level,
            seed_transpiler=args.seed_transpiler,
        )
        isa_circuit = pass_manager.run(bound_circuit)
        if isa_circuit.layout is None:
            raise RuntimeError("Transpilation produced no layout; refusing an unverified observable mapping.")
        isa_hamiltonian = hamiltonian.apply_layout(isa_circuit.layout)
        native_2q_count, operation_counts = _native_two_qubit_count(isa_circuit, backend)
        two_qubit_depth = isa_circuit.depth(filter_function=lambda instruction: len(instruction.qubits) == 2)
        qwc_group_count = len(hamiltonian.group_commuting(qubit_wise=True))
        estimated_executions = (
            qwc_group_count * int(args.shots) if args.shots is not None else None
        )
        # IBM's documented 2 s + 0.35 ms/execution rule is only a rough floor;
        # circuit duration, mitigation, and service batching can increase usage.
        rough_usage_seconds = (
            2.0 + 0.00035 * estimated_executions
            if estimated_executions is not None else None
        )
        calibration = backend.properties()
        calibration_date = getattr(calibration, "last_update_date", None) if calibration else None
        layout = isa_circuit.layout.final_index_layout()

        _progress(
            f"Preflight OK: {isa_circuit.num_qubits} physical-wire circuit, depth={isa_circuit.depth()}, "
            f"native two-qubit gates={native_2q_count}, Pauli terms={len(hamiltonian)}, "
            f"QWC groups={qwc_group_count}, "
            f"saved ideal E={saved_total:.9f} Ha, CASCI={reference['references']['frozen_core_casci_hartree']:.9f} Ha"
        )
        if estimated_executions is not None:
            _progress(
                f"Workload estimate: {estimated_executions:,} group-shot executions; "
                f"IBM quick estimate ≈{rough_usage_seconds:.1f} QPU seconds before circuit/mitigation overhead. "
                "The max_execution_time cap is the actual safety limit."
            )

        Estimator, api_name = _runtime_estimator_class()
        estimator_options: dict[str, Any] = {
            "resilience_level": int(args.resilience_level),
            "max_execution_time": int(args.max_execution_time),
        }
        if args.shots is not None:
            estimator_options["default_shots"] = int(args.shots)
        else:
            estimator_options["default_precision"] = float(args.precision)
        estimator = Estimator(mode=backend, options=estimator_options)
        if args.shots is not None:
            # Keep the shot budget explicit even when readout mitigation is on.
            # At resilience level 1, TREX uses measurement twirling; use a
            # fixed randomization x shots product instead of automatic sizing.
            twirling = estimator.options.twirling
            twirling.enable_gates = False
            twirling.enable_measure = args.resilience_level == 1
            if args.resilience_level == 1:
                randomizations = min(4, args.shots)
                while args.shots % randomizations:
                    randomizations -= 1
                twirling.num_randomizations = randomizations
                twirling.shots_per_randomization = args.shots // randomizations
        _progress(
            f"Requesting {'REAL QPU submission' if args.submit else 'server-side dry run (no QPU execution)'}; "
            f"{'shots/configuration=' + str(args.shots) if args.shots is not None else 'precision target=' + str(args.precision) + ' Ha'}, "
            f"resilience_level={args.resilience_level}, "
            f"max QPU time={args.max_execution_time}s"
        )
        job = estimator.run([(isa_circuit, isa_hamiltonian)], dry_run=not args.submit)
        job_id = job.job_id() if callable(getattr(job, "job_id", None)) else str(getattr(job, "job_id", "unknown"))
        _progress(f"Runtime job created: {job_id}; status={job.status()}")

        output_dir = args.output
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / (
            f"ibm-{backend.name}-r{args.resilience_level}-"
            f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        )
        record: dict[str, Any] = {
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "execution_type": "real_ibm_qpu" if args.submit else "ibm_runtime_dry_run_no_qpu_execution",
            "qpu_job_submitted": bool(args.submit),
            "job_id": str(job_id),
            "job_status_at_submission": str(job.status()),
            "runtime_estimator_api": api_name,
            "backend": str(backend.name),
            "backend_status": str(status),
            "backend_calibration_last_update": _jsonable(calibration_date),
            "transpiler_optimization_level": int(args.optimization_level),
            "physical_layout_final_indices": [int(q) for q in layout],
            "physical_qubit_count": int(isa_circuit.num_qubits),
            "circuit_depth": int(isa_circuit.depth()),
            "two_qubit_depth": int(two_qubit_depth),
            "native_two_qubit_gate_count": native_2q_count,
            "operation_counts": operation_counts,
            "method": method,
            "ansatz_reps": int(row.get("ansatz_reps", 1)),
            "trial": int(row.get("trial", -1)),
            "parameters": int(point.size),
            "pauli_term_count": int(len(hamiltonian)),
            "qubit_wise_commuting_group_count": int(qwc_group_count),
            "rough_estimated_executions": estimated_executions,
            "rough_estimated_qpu_seconds_before_overhead": rough_usage_seconds,
            "saved_ideal_energy_hartree": saved_total,
            "noiseless_rebuilt_energy_hartree": ideal_total,
            "ideal_reconstruction_abs_delta_hartree": ideal_delta,
            "active_space_casci_hartree": float(reference["references"]["frozen_core_casci_hartree"]),
            "target_precision_hartree": (
                float(args.precision) if args.precision is not None else None
            ),
            "shots_per_configuration": int(args.shots) if args.shots is not None else None,
            "resilience_level": int(args.resilience_level),
            "max_execution_time_seconds": int(args.max_execution_time),
            "interpretation": (
                "Dry-run output contains no measured QPU energy; it is used only for workload validation/metadata."
                if not args.submit else
                "Fixed-parameter hardware energy estimate. This is one noisy measurement, not hardware VQE optimization."
            ),
        }
        output_file.write_text(json.dumps(_jsonable(record), indent=2) + "\n", encoding="utf-8")
        _progress(f"Saved submission metadata: {output_file}")

        if args.submit:
            _progress("Waiting for IBM QPU result; do not submit duplicate jobs.")
        else:
            _progress("Waiting for IBM server-side dry-run validation; no QPU execution occurs.")
        while not job.done():
            time.sleep(15)
            _progress(f"Runtime job {job_id}: status={job.status()}")
        result = job.result()

        if args.submit:
            pub = result[0]
            electronic_ev = float(np.real(np.asarray(pub.data.evs).item()))
            std = float(np.real(np.asarray(pub.data.stds).item()))
            qpu_total = electronic_ev + offset
            casci = float(reference["references"]["frozen_core_casci_hartree"])
            record.update({
                "job_status_final": str(job.status()),
                "electronic_energy_hartree": electronic_ev,
                "nuclear_and_frozen_core_offset_hartree": offset,
                "qpu_total_energy_hartree": qpu_total,
                "estimator_reported_std_hartree": std,
                "absolute_error_vs_active_space_casci_hartree": abs(qpu_total - casci),
                "estimator_result_metadata": _jsonable(pub.metadata),
                "runtime_result_metadata": _jsonable(getattr(result, "metadata", {})),
            })
            try:
                usage = job.usage()
                record["qpu_usage_seconds"] = _jsonable(usage)
            except Exception as exc:  # usage reporting can be unavailable to some account roles
                record["qpu_usage_unavailable_reason"] = f"{type(exc).__name__}: {exc}"
            output_file.write_text(json.dumps(_jsonable(record), indent=2) + "\n", encoding="utf-8")
            _progress(
                f"QPU result E={qpu_total:+.9f} Ha ± {std:.3g} Ha; "
                f"|Δ active CASCI|={abs(qpu_total-casci)*1000:.3f} mHa"
            )
            _progress(f"Saved QPU result: {output_file}")
        else:
            record["dry_run_result_metadata"] = _jsonable(getattr(result, "metadata", {}))
            try:
                record["dry_run_usage_estimate"] = _jsonable(job.usage())
            except Exception as exc:
                record["dry_run_usage_unavailable_reason"] = f"{type(exc).__name__}: {exc}"
            output_file.write_text(json.dumps(_jsonable(record), indent=2) + "\n", encoding="utf-8")
            _progress("Dry run only: no QPU energy was measured and no hardware usage was consumed.")
            _progress(f"Dry-run result metadata: {record.get('dry_run_result_metadata', {})}")
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
