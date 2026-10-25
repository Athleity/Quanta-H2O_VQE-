#!/usr/bin/env python3
"""Evaluate saved H2O VQE optima with finite-shot synthetic Aer noise.

This is a fixed-parameter robustness test, not noisy VQE optimization or a
hardware benchmark. It rebuilds the chemistry Hamiltonian from the saved
geometry, then measures the saved optimized circuit under an explicit noise
model and independent simulator seeds.
"""

from __future__ import annotations
# INSTALL COMMAND (Quanta VQE)
# From the repository root, install dependencies with:
# python -m pip install --prefer-binary -r config/requirements/requirements-noise.txt


import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .engine import Geometry, _require_scientific_stack, build_active_problem


def evaluate(
    run_dir: Path,
    *,
    shots: int,
    seeds: list[int],
    p1: float,
    p2: float,
    readout: float,
    methods: list[str],
) -> dict[str, Any]:
    try:
        from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error
        from qiskit_aer.primitives import Estimator
    except ImportError as exc:
        raise RuntimeError(
            "Noisy evaluation requires Qiskit Aer. Install it in the active WSL "
            "environment with: python -m pip install -r config/requirements/requirements-noise.txt"
        ) from exc

    summary_path = run_dir / "summary.json"
    reference_path = run_dir / "reference.json"
    if not summary_path.is_file() or not reference_path.is_file():
        raise FileNotFoundError(f"expected summary.json and reference.json under {run_dir}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    metadata = json.loads(reference_path.read_text(encoding="utf-8"))
    candidates = [
        row for row in summary.get("vqe_runs", [])
        if row.get("method") in set(methods)
        and row.get("optimal_point") is not None
    ]
    if not candidates:
        raise ValueError(
            "No saved fixed-ansatz optimum found. Rerun with the updated scripts/compat/h2o_vqe.py; "
            "older summaries do not store optimal_point."
        )
    # Evaluate the best converged or capped fixed-ansatz result for each ansatz;
    # retaining the optimizer flag prevents this selection from implying convergence.
    selected: dict[str, dict[str, Any]] = {}
    for row in candidates:
        name = row["method"]
        if name not in selected or row["total_energy_hartree"] < selected[name]["total_energy_hartree"]:
            selected[name] = row

    geometry = Geometry(**metadata["geometry"])
    atom = geometry.pyscf_atom_spec()
    active_problem, mapper, hamiltonian, mapping = build_active_problem(atom)
    num_measurement_groups = len(hamiltonian.group_commuting())
    stack = _require_scientific_stack()
    noise = NoiseModel()
    if p1:
        noise.add_all_qubit_quantum_error(
            depolarizing_error(p1, 1), ["x", "rx", "ry"]
        )
    if p2:
        noise.add_all_qubit_quantum_error(depolarizing_error(p2, 2), ["cx"])
    if readout:
        noise.add_all_qubit_readout_error(
            ReadoutError([[1.0 - readout, readout], [readout, 1.0 - readout]])
        )

    results: list[dict[str, Any]] = []
    for method, row in selected.items():
        n_orb = int(active_problem.num_spatial_orbitals)
        n_particles = active_problem.num_particles
        hf_state = stack["HartreeFock"](n_orb, n_particles, mapper)
        ansatz_cls = {"uccsd": stack["UCCSD"], "puccsd": stack["PUCCSD"]}[method]
        circuit = ansatz_cls(
            n_orb,
            n_particles,
            mapper,
            reps=int(row.get("ansatz_reps", 1)),
            initial_state=hf_state,
        )
        circuit = stack["transpile"](
            circuit,
            basis_gates=["x", "rx", "ry", "rz", "cx"],
            optimization_level=0,
        )
        point = np.asarray(row["optimal_point"], dtype=float)
        if point.shape != (circuit.num_parameters,):
            raise ValueError(
                f"saved {method} parameter vector has {point.size} entries; "
                f"rebuilt circuit expects {circuit.num_parameters}"
            )

        energies: list[float] = []
        for seed in seeds:
            estimator = Estimator(
                backend_options={"noise_model": noise},
                run_options={"shots": shots, "seed": seed},
                approximation=False,
                abelian_grouping=True,
            )
            result = estimator.run(
                circuits=[circuit],
                observables=[hamiltonian],
                parameter_values=[point],
            ).result()
            # The saved offset converts the mapped active electronic expectation
            # to total molecular energy under Qiskit Nature's convention.
            energies.append(
                float(np.real(result.values[0]))
                + float(row["total_energy_offset_hartree"])
            )
        casci = float(metadata["references"]["frozen_core_casci_hartree"])
        results.append(
            {
                "method": method,
                "optimizer": row.get("optimizer"),
                "optimizer_success": row.get("optimizer_success"),
                "noise_free_energy_hartree": row["total_energy_hartree"],
                "noise_free_abs_error_vs_active_casci_hartree": abs(
                    row["total_energy_hartree"] - casci
                ),
                "noisy_total_energy_by_seed_hartree": energies,
                "noisy_mean_energy_hartree": float(np.mean(energies)),
                "noisy_std_across_seeds_hartree": (
                    float(np.std(energies, ddof=1)) if len(energies) > 1 else None
                ),
                "noisy_abs_error_vs_active_casci_hartree": abs(
                    float(np.mean(energies)) - casci
                ),
                "num_parameters": row["num_parameters"],
                "cx_count_level_0": row["ansatz_cx_count"],
                "shots_per_commuting_group_per_seed": shots,
            }
        )

    return {
        "model": "fixed optimized state evaluated with finite shots and synthetic gate/readout noise",
        "not_a_noisy_optimization": True,
        "not_hardware_data": True,
        "geometry": metadata["geometry"],
        "mapped_qubits": mapping["mapped_qubits"],
        "noise_model": {
            "one_qubit_depolarizing_probability_on_x_rx_ry": p1,
            "two_qubit_depolarizing_probability_on_cx": p2,
            "symmetric_readout_bit_flip_probability": readout,
            "rz_noise": "none (modeled as virtual in this illustrative channel)",
        },
        "shots_per_commuting_group_per_seed": shots,
        "commuting_measurement_groups": num_measurement_groups,
        "estimated_total_shots_per_method": shots * num_measurement_groups * len(seeds),
        "seeds": seeds,
        "active_casci_reference_hartree": float(
            metadata["references"]["frozen_core_casci_hartree"]
        ),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="directory containing summary.json and reference.json")
    parser.add_argument("--shots", type=int, default=1000)
    parser.add_argument("--seeds", default="11,29,47")
    parser.add_argument(
        "--methods", default="puccsd",
        help="comma-separated fixed ansätze to evaluate (default puccsd keeps the noisy run compact)",
    )
    parser.add_argument("--one-qubit-depol", type=float, default=1e-4)
    parser.add_argument("--two-qubit-depol", type=float, default=1e-3)
    parser.add_argument("--readout-error", type=float, default=0.01)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.shots < 1:
        parser.error("--shots must be positive")
    try:
        seeds = [int(value.strip()) for value in args.seeds.split(",") if value.strip()]
    except ValueError as exc:
        parser.error(f"invalid --seeds: {exc}")
    if not seeds or len(set(seeds)) != len(seeds):
        parser.error("--seeds must be nonempty and unique")
    probabilities = (args.one_qubit_depol, args.two_qubit_depol, args.readout_error)
    if any(not np.isfinite(p) or not (0.0 <= p < 1.0) for p in probabilities):
        parser.error("all noise probabilities must be finite and in [0, 1)")
    methods = [name.strip().lower() for name in args.methods.split(",") if name.strip()]
    if not methods or len(set(methods)) != len(methods) or set(methods) - {"uccsd", "puccsd"}:
        parser.error("--methods must be a nonempty unique list containing uccsd and/or puccsd")
    try:
        output = evaluate(
            args.run_dir.resolve(),
            shots=args.shots,
            seeds=seeds,
            p1=args.one_qubit_depol,
            p2=args.two_qubit_depol,
            readout=args.readout_error,
            methods=methods,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    target = args.output or (args.run_dir / "noisy_energy.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, indent=2), encoding="utf-8")
    for row in output["results"]:
        print(
            f"{row['method']:8s} noisy mean={row['noisy_mean_energy_hartree']:.9f} Ha "
            f"|ΔCASCI|={row['noisy_abs_error_vs_active_casci_hartree'] * 1000:.3f} mHa "
            f"seed-sd={row['noisy_std_across_seeds_hartree']} Ha"
        )
    print(f"Saved noisy evaluation to: {target.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
