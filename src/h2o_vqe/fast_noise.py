"""Fast finite-shot noisy-Aer evaluation of a saved H2O VQE optimum.

This evaluates a fixed, already-optimized 10-qubit state. It is not a noisy
VQE optimization and the explicit depolarizing/readout channel is a synthetic
illustrative model, not IBM calibration data or QPU output. Qubit-wise
commuting Hamiltonian groups are sampled in small batches so partial progress
is visible and recoverable while the full energy is being assembled.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from .engine import Geometry, _require_scientific_stack, build_active_problem


BASIS_GATES = ["x", "rx", "ry", "rz", "cx", "h", "sdg"]


def _atomic_json(path: Path, content: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _load_best(run_dir: Path, method: str) -> tuple[dict[str, Any], dict[str, Any]]:
    summary_file = run_dir / "summary.json"
    reference_file = run_dir / "reference.json"
    if not summary_file.is_file() or not reference_file.is_file():
        raise FileNotFoundError(
            f"Expected summary.json and reference.json in {run_dir}"
        )
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    reference = json.loads(reference_file.read_text(encoding="utf-8"))
    rows = [
        row for row in summary.get("vqe_runs", [])
        if row.get("method") == method and row.get("optimal_point") is not None
    ]
    if not rows:
        raise ValueError(
            f"No saved {method} parameter vector in {summary_file}; "
            "run a VQE optimization that stores optimal_point first."
        )
    return min(rows, key=lambda row: float(row["total_energy_hartree"])), reference


def _make_group_circuit(bound_circuit: Any, group: Any) -> tuple[Any, list[tuple[str, float, list[int]]]]:
    """Add QWC basis rotations and return term labels, coefficients, supports."""
    n_qubits = bound_circuit.num_qubits
    basis = ["I"] * n_qubits
    labels = group.paulis.to_labels()
    coeffs = np.asarray(group.coeffs, dtype=complex)
    terms: list[tuple[str, float, list[int]]] = []
    for label, coeff in zip(labels, coeffs, strict=True):
        if abs(float(np.imag(coeff))) > 1e-10:
            raise ValueError("Hamiltonian group contains a non-real coefficient")
        support: list[int] = []
        for qubit, pauli in enumerate(reversed(label)):
            if pauli != "I":
                support.append(qubit)
                if basis[qubit] not in ("I", pauli):
                    raise ValueError("Input group is not qubit-wise commuting")
                basis[qubit] = pauli
        terms.append((label, float(np.real(coeff)), support))

    circuit = bound_circuit.copy()
    for qubit, pauli in enumerate(basis):
        if pauli == "X":
            circuit.h(qubit)
        elif pauli == "Y":
            circuit.sdg(qubit)
            circuit.h(qubit)
    circuit.measure_all()
    return circuit, terms


def _group_statistics(
    counts: dict[str, int], terms: list[tuple[str, float, list[int]]], shots: int
) -> tuple[float, float]:
    """Return group sample mean and standard error, preserving term covariance."""
    weighted_first = 0.0
    weighted_second = 0.0
    counted = 0
    for raw_bits, count in counts.items():
        bits = raw_bits.replace(" ", "")
        value = 0.0
        for _label, coefficient, support in terms:
            parity = sum(bits[-1 - qubit] == "1" for qubit in support) & 1
            value += coefficient * (1.0 if parity == 0 else -1.0)
        weighted_first += count * value
        weighted_second += count * value * value
        counted += count
    if counted != shots:
        raise RuntimeError(f"Simulator returned {counted} shots; expected {shots}")
    mean = weighted_first / shots
    if shots < 2:
        return mean, float("nan")
    sample_variance = max(
        0.0,
        (weighted_second - shots * mean * mean) / (shots - 1),
    )
    return mean, math.sqrt(sample_variance / shots)


def run_study(args: argparse.Namespace) -> dict[str, Any]:
    try:
        from qiskit import transpile
        from qiskit.quantum_info import Statevector
        from qiskit_aer import AerSimulator
        from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error
    except ImportError as exc:
        raise RuntimeError(
            "Install the project's Aer dependency in the active noise environment: "
            "python -m pip install --prefer-binary -r requirements-noise.txt"
        ) from exc

    row, reference = _load_best(args.run_dir.resolve(), args.method)
    if "geometry" not in reference or "references" not in reference:
        raise ValueError("reference.json is missing geometry or reference energies")
    geometry = Geometry(**reference["geometry"])
    problem, mapper, hamiltonian, mapping = build_active_problem(
        geometry.pyscf_atom_spec()
    )
    stack = _require_scientific_stack()
    ansatz_type = {"uccsd": stack["UCCSD"], "puccsd": stack["PUCCSD"]}[args.method]
    hf = stack["HartreeFock"](
        int(problem.num_spatial_orbitals), problem.num_particles, mapper
    )
    ansatz = ansatz_type(
        int(problem.num_spatial_orbitals),
        problem.num_particles,
        mapper,
        reps=int(row.get("ansatz_reps", 1)),
        initial_state=hf,
    )
    point = np.asarray(row["optimal_point"], dtype=float)
    if point.shape != (ansatz.num_parameters,):
        raise ValueError(
            f"Saved vector has {point.size} values; rebuilt ansatz requires "
            f"{ansatz.num_parameters}."
        )
    bound = ansatz.assign_parameters(
        dict(zip(ansatz.parameters, point, strict=True)), inplace=False
    )
    print(
        f"Loaded saved {args.method} reps={row.get('ansatz_reps')} optimum: "
        f"{ansatz.num_qubits} logical qubits, {ansatz.num_parameters} parameters; "
        "checking ideal energy",
        flush=True,
    )
    ideal_electronic = float(
        np.real(Statevector.from_instruction(bound).expectation_value(hamiltonian))
    )
    offset = float(row["total_energy_offset_hartree"])
    ideal_total = ideal_electronic + offset
    saved_total = float(row["total_energy_hartree"])
    if abs(ideal_total - saved_total) > 1e-7:
        raise ValueError(
            f"Rebuilt ideal energy {ideal_total:.12f} Ha disagrees with saved "
            f"{saved_total:.12f} Ha; refusing a mismatched noise run."
        )
    casci = float(reference["references"]["frozen_core_casci_hartree"])
    print(
        f"Ideal check passed: E={ideal_total:+.9f} Ha; "
        f"|ΔCASCI|={abs(ideal_total - casci) * 1000:.3f} mHa",
        flush=True,
    )

    print("Building 10-qubit noisy Aer simulator and measurement groups...", flush=True)
    noise = NoiseModel()
    if args.one_qubit_depol:
        noise.add_all_qubit_quantum_error(
            depolarizing_error(args.one_qubit_depol, 1),
            # Rz and Sdg are virtual frame changes in this toy gate model;
            # apply stochastic one-qubit error to physical rotations and H.
            ["x", "rx", "ry", "h"],
        )
    if args.two_qubit_depol:
        noise.add_all_qubit_quantum_error(
            depolarizing_error(args.two_qubit_depol, 2), ["cx"]
        )
    if args.readout_error:
        probability = args.readout_error
        noise.add_all_qubit_readout_error(
            ReadoutError(
                [[1.0 - probability, probability], [probability, 1.0 - probability]]
            )
        )
    simulator = AerSimulator(
        method="matrix_product_state",
        noise_model=noise,
        basis_gates=BASIS_GATES,
        max_parallel_threads=1,
    )

    groups = hamiltonian.group_commuting(qubit_wise=True)
    if not groups:
        raise RuntimeError("No qubit-wise commuting groups were produced")
    # Bind first and compile only the 10 active logical qubits. This avoids the
    # 100+ idle physical wires of a fake IBM backend, which slowed the prior run.
    # H and Sdg remain explicit basis gates so each measurement group can add
    # its basis rotations without retranspiling the full ansatz hundreds of times.
    logical_bound = transpile(
        bound, basis_gates=BASIS_GATES, optimization_level=0, seed_transpiler=11
    )
    measurement_circuits: list[Any] = []
    group_terms: list[list[tuple[str, float, list[int]]]] = []
    for group_index, group in enumerate(groups, start=1):
        measured, terms = _make_group_circuit(logical_bound, group)
        measurement_circuits.append(measured)
        group_terms.append(terms)
        if group_index % 50 == 0 or group_index == len(groups):
            print(f"Prepared measurement circuits {group_index}/{len(groups)}", flush=True)

    total_group_rows: list[dict[str, Any]] = []
    seed_energies: list[dict[str, Any]] = []
    output = args.output.resolve()
    checkpoint = output.with_name(output.stem + "_progress.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    total_started = time.perf_counter()
    print(
        f"Starting synthetic-noise sampling: {len(groups)} QWC groups, "
        f"{args.shots} shots/group, {len(args.seeds)} seed(s), "
        f"{len(groups) * args.shots * len(args.seeds):,} shots total",
        flush=True,
    )

    for seed_index, seed in enumerate(args.seeds, start=1):
        seed_started = time.perf_counter()
        partial = 0.0
        variance = 0.0
        seed_rows: list[dict[str, Any]] = []
        batches = math.ceil(len(groups) / args.batch_size)
        for batch_index, start in enumerate(
            range(0, len(groups), args.batch_size), start=1
        ):
            end = min(start + args.batch_size, len(groups))
            print(
                f"[seed {seed_index}/{len(args.seeds)}={seed}] batch "
                f"{batch_index}/{batches}, groups {start + 1}-{end}/{len(groups)}",
                flush=True,
            )
            batch_seed = (seed * 1_000_003 + batch_index) % (2**32 - 1)
            job = simulator.run(
                measurement_circuits[start:end],
                shots=args.shots,
                seed_simulator=batch_seed,
            )
            result = job.result()
            for local_index, group_index in enumerate(range(start, end)):
                counts = result.get_counts(local_index)
                contribution, standard_error = _group_statistics(
                    counts, group_terms[group_index], args.shots
                )
                partial += contribution
                variance += standard_error * standard_error
                group_row = {
                    "seed": seed,
                    "group_index": group_index + 1,
                    "group_energy_contribution_hartree": contribution,
                    "group_standard_error_hartree": standard_error,
                    "partial_sum_hartree": partial,
                    "is_full_energy": group_index + 1 == len(groups),
                }
                seed_rows.append(group_row)
                total_group_rows.append(group_row)
                print(
                    f"  group {group_index + 1}/{len(groups)}: "
                    f"ΔE_group={contribution:+.7f} Ha; "
                    f"partial H sum={partial:+.7f} Ha "
                    "(not yet the full energy)",
                    flush=True,
                )
            checkpoint_data = {
                "status": "running",
                "method": args.method,
                "ansatz_reps": int(row.get("ansatz_reps", 1)),
                "seed": seed,
                "groups_completed_for_seed": len(seed_rows),
                "groups_total": len(groups),
                "partial_hamiltonian_sum_hartree": partial,
                "partial_is_full_energy": len(seed_rows) == len(groups),
                "completed_seed_energies": seed_energies,
                "group_results_for_current_seed": seed_rows,
                "updated_unix_time": time.time(),
            }
            _atomic_json(checkpoint, checkpoint_data)

        total_energy = partial + offset
        total_se = math.sqrt(variance)
        seed_record = {
            "seed": seed,
            "total_energy_hartree": total_energy,
            "standard_error_hartree": total_se,
            "absolute_error_vs_active_casci_hartree": abs(total_energy - casci),
        }
        seed_energies.append(seed_record)
        print(
            f"[seed {seed}] COMPLETE noisy E={total_energy:+.9f} Ha ± "
            f"{total_se:.6f} Ha (sampling SE); "
            f"|ΔCASCI|={abs(total_energy - casci) * 1000:.3f} mHa; "
            f"elapsed={time.perf_counter() - seed_started:.1f}s",
            flush=True,
        )
        _atomic_json(
            checkpoint,
            {
                "status": "complete" if seed_index == len(args.seeds) else "running",
                "method": args.method,
                "ansatz_reps": int(row.get("ansatz_reps", 1)),
                "completed_seed_energies": seed_energies,
                "last_completed_seed": seed,
                "groups_total": len(groups),
                "updated_unix_time": time.time(),
            },
        )

    energies = np.asarray([item["total_energy_hartree"] for item in seed_energies])
    seed_sds = np.asarray([item["standard_error_hartree"] for item in seed_energies])
    mean_energy = float(np.mean(energies))
    mean_sampling_se = float(np.sqrt(np.sum(seed_sds**2)) / len(seed_sds))
    payload = {
        "study_type": "fixed-parameter, synthetic finite-shot noisy Aer evaluation",
        "not_noisy_optimization": True,
        "not_ibm_hardware_or_backend_calibration": True,
        "geometry": reference["geometry"],
        "mapped_qubits": mapping["mapped_qubits"],
        "method": args.method,
        "ansatz_reps": int(row.get("ansatz_reps", 1)),
        "num_parameters": int(ansatz.num_parameters),
        "ideal_energy_hartree": ideal_total,
        "active_casci_reference_hartree": casci,
        "ideal_abs_error_vs_casci_hartree": abs(ideal_total - casci),
        "noise_model": {
            "one_qubit_depolarizing_probability_on_x_rx_ry_h": args.one_qubit_depol,
            "two_qubit_depolarizing_probability_on_cx": args.two_qubit_depol,
            "symmetric_readout_bit_flip_probability": args.readout_error,
            "rz_channel": "none; treated as virtual",
        },
        "measurement": {
            "grouping": "qubit-wise commuting",
            "groups": len(groups),
            "shots_per_group": args.shots,
            "seeds": args.seeds,
            "total_shots_per_seed": len(groups) * args.shots,
            "basis_gates": BASIS_GATES,
        },
        "noisy_energy_by_seed": seed_energies,
        "noisy_mean_energy_hartree": mean_energy,
        "propagated_sampling_standard_error_of_mean_hartree": mean_sampling_se,
        "noisy_mean_abs_error_vs_casci_hartree": abs(mean_energy - casci),
        "noise_bias_vs_ideal_hartree": mean_energy - ideal_total,
        "wall_time_seconds": time.perf_counter() - total_started,
        "interpretation": [
            "This is a synthetic depolarizing plus readout noise demonstration, not a calibrated IBM-device prediction.",
            "Only the completed sum over every Hamiltonian group is a full energy estimate; intermediate partial sums are not energies.",
            "A finite-shot noisy estimate can fall below the active-space CASCI value; that does not imply a better variational state.",
            "The uncertainty covers finite-sampling noise only, not uncertainty in the chosen synthetic noise rates.",
        ],
        "group_results": total_group_rows,
    }
    _atomic_json(output, payload)
    report = output.with_name(output.stem + "_report.md")
    report.write_text(
        "\n".join(
            [
                "# H₂O noisy simulator result",
                "",
                "This is a fixed optimized PUCCSD/UCCSD state evaluated with finite shots in local Aer under the explicitly stated synthetic noise model. It is not IBM hardware data.",
                "",
                f"- Ansatz: {args.method}, reps={int(row.get('ansatz_reps', 1))}, {ansatz.num_parameters} parameters.",
                f"- Qubits: {mapping['mapped_qubits']}; QWC measurement groups: {len(groups)}.",
                f"- Shots/group: {args.shots}; seeds: {', '.join(map(str, args.seeds))}.",
                f"- Ideal saved energy: {ideal_total:.9f} Ha (|ΔCASCI|={abs(ideal_total-casci)*1000:.3f} mHa).",
                f"- Noisy mean: {mean_energy:.9f} ± {mean_sampling_se:.6f} Ha (propagated sampling SE).",
                f"- Noise bias vs ideal: {(mean_energy-ideal_total)*1000:+.3f} mHa.",
                f"- Noisy |ΔCASCI|: {abs(mean_energy-casci)*1000:.3f} mHa.",
                f"- Synthetic model: p1={args.one_qubit_depol:g}, p2={args.two_qubit_depol:g}, readout={args.readout_error:g}.",
                "",
                "Interpretation: the run demonstrates finite-shot noisy simulation of the saved H₂O ansatz. It does not demonstrate noisy re-optimization, error mitigation, or real-device performance. The sampling uncertainty excludes uncertainty in the synthetic noise rates.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Saved result: {output}", flush=True)
    print(f"Saved presentation note: {report}", flush=True)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=Path("results/ansatz/ansatz-resource-pilot/puccsd-reps1"),
        help="saved VQE result directory containing summary.json and reference.json",
    )
    parser.add_argument("--method", choices=("puccsd", "uccsd"), default="puccsd")
    parser.add_argument("--shots", type=int, default=64,
                        help="exact shots per QWC group on local Aer; lower is faster but noisier")
    parser.add_argument("--batch-size", type=int, default=12,
                        help="measurement groups per Aer submission; smaller batches show progress sooner")
    parser.add_argument("--seeds", default="11", help="comma-separated independent simulator seeds")
    parser.add_argument("--one-qubit-depol", type=float, default=1e-4)
    parser.add_argument("--two-qubit-depol", type=float, default=1e-3)
    parser.add_argument("--readout-error", type=float, default=0.01)
    parser.add_argument("--output", type=Path,
                        default=Path("results/noisy-demo/noisy_energy.json"))
    args = parser.parse_args()
    if args.shots < 2:
        parser.error("--shots must be at least 2 to estimate sampling uncertainty")
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    try:
        args.seeds = [int(value.strip()) for value in args.seeds.split(",") if value.strip()]
    except ValueError:
        parser.error("--seeds must be comma-separated integers")
    if not args.seeds or len(set(args.seeds)) != len(args.seeds):
        parser.error("--seeds must be nonempty and unique")
    probabilities = (args.one_qubit_depol, args.two_qubit_depol, args.readout_error)
    if any(not np.isfinite(p) or p < 0.0 or p >= 1.0 for p in probabilities):
        parser.error("noise probabilities must be finite and in [0, 1)")
    try:
        run_study(args)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
