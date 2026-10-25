#!/usr/bin/env python3
"""Reproducible H2O asymmetric O-H extension benchmark (STO-3G).

The electronic structure is generated from geometry by PySCF.  The quantum
benchmark uses a frozen-core CAS(8e,6o) model (12 spin orbitals), and checks
that model against both PySCF CASCI and an independently mapped Qiskit exact
solver before running any VQE.  Energies are never hard-coded.

This is an ideal statevector algorithm study.  It does not model device noise
or claim hardware performance.
"""

from __future__ import annotations
# INSTALL COMMAND (Quanta VQE)
# From the repository root, install dependencies with:
# python -m pip install --prefer-binary -r config/requirements/requirements-wsl.txt


import argparse
import csv
import json
import logging
import math
import platform
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np


HARTREE_TO_MILLIHARTREE = 1000.0
CHEMICAL_ACCURACY_HA = 0.0016
DEFAULT_RHF_BOND_ANGSTROM = 0.96
DEFAULT_STRETCHED_BOND_ANGSTROM = 2.20
DEFAULT_ANGLE_DEG = 104.5
ACTIVE_ELECTRONS = (4, 4)
ACTIVE_SPATIAL_ORBITALS = 6


def _json_default(value: Any) -> Any:
    """Convert common scientific Python scalars into strict JSON values.

    SciPy/Qiskit optimizer results can contain NumPy scalar types (notably
    ``numpy.int64`` for evaluation counts), which the standard JSON encoder
    does not serialize even though they behave like native Python numbers.
    Keep this conversion explicit so saved results remain portable JSON.
    """
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


@dataclass(frozen=True)
class Geometry:
    fixed_oh_angstrom: float = DEFAULT_RHF_BOND_ANGSTROM
    stretched_oh_angstrom: float = DEFAULT_STRETCHED_BOND_ANGSTROM
    hoh_angle_deg: float = DEFAULT_ANGLE_DEG

    def validate(self) -> None:
        if not (0.3 <= self.fixed_oh_angstrom <= 3.5):
            raise ValueError("fixed O-H distance must be between 0.3 and 3.5 Å")
        if not (0.3 <= self.stretched_oh_angstrom <= 8.0):
            raise ValueError("stretched O-H distance must be between 0.3 and 8.0 Å")
        if not (20.0 <= self.hoh_angle_deg <= 170.0):
            raise ValueError("H-O-H angle must be between 20 and 170 degrees")

    def pyscf_atom_spec(self) -> str:
        """Place one H on +z and the second in the xz plane at the given angle."""
        self.validate()
        theta = math.radians(self.hoh_angle_deg)
        x2 = self.stretched_oh_angstrom * math.sin(theta)
        z2 = self.stretched_oh_angstrom * math.cos(theta)
        return (
            f"O 0.0 0.0 0.0; "
            f"H 0.0 0.0 {self.fixed_oh_angstrom:.12g}; "
            f"H {x2:.12g} 0.0 {z2:.12g}"
        )


def _require_scientific_stack() -> dict[str, Any]:
    """Import optional heavy dependencies only after argument parsing."""
    try:
        import scipy
        import pyscf
        from pyscf import fci, gto, mcscf, scf
        from qiskit import transpile
        from qiskit.primitives import StatevectorEstimator
        from qiskit_algorithms import AdaptVQE, NumPyMinimumEigensolver, VQE
        from qiskit_algorithms.gradients import ReverseEstimatorGradient
        from qiskit_algorithms.optimizers import (
            COBYLA,
            L_BFGS_B,
            OptimizerResult,
            POWELL,
            SPSA,
            SLSQP,
        )
        from qiskit_algorithms.utils import algorithm_globals
        import qiskit
        import qiskit_algorithms
        import qiskit_nature
        from qiskit_nature.second_q.algorithms import GroundStateEigensolver
        from qiskit_nature.second_q.circuit.library import HartreeFock, PUCCSD, UCCSD
        from qiskit_nature.second_q.drivers import PySCFDriver
        from qiskit_nature.second_q.mappers import ParityMapper
        from qiskit_nature.second_q.transformers import ActiveSpaceTransformer
        from qiskit_nature.units import DistanceUnit
    except ImportError as exc:
        raise RuntimeError(
            f"Missing Python module {exc.name!r}. In the active Ubuntu/WSL project "
            "venv, run: python -m pip install --prefer-binary "
            "-r config/requirements/requirements-wsl.txt"
        ) from exc

    return locals()


def calculate_references(atom: str) -> dict[str, Any]:
    """Compute RHF, all-electron STO-3G FCI, and frozen-core CAS(8,6) CASCI."""
    stack = _require_scientific_stack()
    gto, scf, fci, mcscf = (stack[k] for k in ("gto", "scf", "fci", "mcscf"))

    mol = gto.M(
        atom=atom,
        unit="Angstrom",
        basis="sto-3g",
        charge=0,
        spin=0,
        symmetry=False,
        verbose=0,
    )
    mean_field = scf.RHF(mol)
    mean_field.conv_tol = 1e-11
    mean_field.max_cycle = 200
    e_hf = float(mean_field.kernel())
    if not mean_field.converged:
        # Newton-SCF is a recovery path for difficult stretched geometries.
        mean_field = mean_field.newton()
        mean_field.conv_tol = 1e-10
        mean_field.max_cycle = 200
        e_hf = float(mean_field.kernel())
    if not mean_field.converged:
        raise RuntimeError("RHF failed to converge, including the Newton-SCF retry")

    # A converged SCF solution can still be a saddle point. Record internal
    # and RHF-to-UHF external stability so stretched-bond scans flag this risk.
    # Use PySCF's public mean-field method: reaching for `scf.stability`
    # assumes the submodule has already been imported and fails on a clean
    # PySCF import in some releases.
    _, _, rhf_internal_stable, rhf_external_stable = mean_field.stability(
        internal=True, external=True, return_status=True
    )

    full_fci_solver = fci.FCI(mean_field)
    full_fci_solver.conv_tol = 1e-10
    full_fci_solver.max_cycle = 200
    # For this 7-orbital, 10-electron closed-shell system the fixed-Ms
    # determinant space has only 441 determinants. Raise PySCF's default
    # p-space threshold (400) to the full dimension so FCI diagonalizes the
    # complete space directly instead of relying on a single RHF-seeded
    # Davidson subspace, which can miss a lower root in another symmetry block.
    n_alpha, n_beta = mol.nelec
    full_fci_dimension = math.comb(mol.nao_nr(), n_alpha) * math.comb(
        mol.nao_nr(), n_beta
    )
    full_fci_solver.pspace_size = full_fci_dimension
    e_full_fci = float(full_fci_solver.kernel()[0])
    if not bool(full_fci_solver.converged):
        raise RuntimeError("Full STO-3G FCI solver did not converge")

    # Water/STO-3G has 10 electrons in 7 spatial orbitals. CAS(8e,6o)
    # leaves the lowest doubly occupied orbital inactive (the O 1s core in
    # this minimal basis) while retaining all six valence spatial orbitals.
    cas = mcscf.CASCI(mean_field, ACTIVE_SPATIAL_ORBITALS, ACTIVE_ELECTRONS)
    cas.conv_tol = 1e-10
    e_casci = float(cas.kernel()[0])
    if cas.ci is None or not np.isfinite(e_casci):
        raise RuntimeError("PySCF CASCI returned no valid active-space solution")
    if e_full_fci > e_casci + 1e-7:
        raise RuntimeError(
            "Full STO-3G FCI energy is above frozen-core CASCI by "
            f"{(e_full_fci - e_casci) * 1000:.6f} mHa. Since the full FCI space "
            "contains the frozen-core CASCI subspace, this signals an inconsistent "
            "or unconverged reference calculation."
        )
    active_rdm1 = cas.fcisolver.make_rdm1(cas.ci, cas.ncas, cas.nelecas)
    natural_occupations = np.linalg.eigvalsh(np.asarray(active_rdm1))[::-1]

    return {
        "rhf_hartree": e_hf,
        "full_sto3g_fci_hartree": e_full_fci,
        "full_sto3g_fci_converged": bool(full_fci_solver.converged),
        "full_sto3g_fci_determinant_dimension": int(full_fci_dimension),
        "full_sto3g_fci_pspace_size": int(full_fci_solver.pspace_size),
        "frozen_core_casci_hartree": e_casci,
        "active_space_bias_vs_full_fci_hartree": e_casci - e_full_fci,
        "active_natural_occupations": [float(x) for x in natural_occupations],
        "num_electrons": int(mol.nelectron),
        "num_spatial_orbitals_full": int(mol.nao_nr()),
        "active_electrons_alpha_beta": list(ACTIVE_ELECTRONS),
        "active_spatial_orbitals": ACTIVE_SPATIAL_ORBITALS,
        "casci_inactive_orbitals": int(cas.ncore),
        "casci_active_mo_indices_zero_based": list(
            range(int(cas.ncore), int(cas.ncore + cas.ncas))
        ),
        "scf_converged": bool(mean_field.converged),
        "rhf_internal_stable": (
            None if rhf_internal_stable is None else bool(rhf_internal_stable)
        ),
        "rhf_external_stable": (
            None if rhf_external_stable is None else bool(rhf_external_stable)
        ),
    }


def build_active_problem(atom: str) -> tuple[Any, Any, Any, dict[str, Any]]:
    """Build the same CAS(8,6) problem through Qiskit Nature's PySCF driver."""
    stack = _require_scientific_stack()
    driver = stack["PySCFDriver"](
        atom=atom,
        unit=stack["DistanceUnit"].ANGSTROM,
        basis="sto3g",
        charge=0,
        spin=0,
    )
    full_problem = driver.run()
    transformer = stack["ActiveSpaceTransformer"](
        num_electrons=ACTIVE_ELECTRONS,
        num_spatial_orbitals=ACTIVE_SPATIAL_ORBITALS,
    )
    active_problem = transformer.transform(full_problem)
    mapper = stack["ParityMapper"](num_particles=active_problem.num_particles)
    mapped_hamiltonian = mapper.map(active_problem.hamiltonian.second_q_op())
    metadata = {
        "qiskit_nature_full_spatial_orbitals": int(full_problem.num_spatial_orbitals),
        "qiskit_nature_full_particles": list(full_problem.num_particles),
        "active_spatial_orbitals": int(active_problem.num_spatial_orbitals),
        "active_particles": list(active_problem.num_particles),
        "qubits_before_mapper_reduction": 2 * int(active_problem.num_spatial_orbitals),
        "mapped_qubits": int(mapped_hamiltonian.num_qubits),
        "mapper": "ParityMapper with particle-number reduction",
        "pauli_terms": int(len(mapped_hamiltonian)),
    }
    return active_problem, mapper, mapped_hamiltonian, metadata


def verify_qubit_exact(active_problem: Any, mapper: Any, expected_casci: float) -> float:
    """Independently solve the mapped operator, filtering to the physical sector."""
    stack = _require_scientific_stack()
    exact_solver = stack["NumPyMinimumEigensolver"]()
    exact_solver.filter_criterion = active_problem.get_default_filter_criterion()
    ground_solver = stack["GroundStateEigensolver"](mapper, exact_solver)
    exact_result = ground_solver.solve(active_problem)
    e_qubit = float(np.real(exact_result.total_energies[0]))
    difference = abs(e_qubit - expected_casci)
    if difference > 2e-7:
        raise RuntimeError(
            "Independent mapped exact solve disagrees with PySCF CASCI: "
            f"{e_qubit:.12f} vs {expected_casci:.12f} Ha (|Δ|={difference:.3e} Ha). "
            "Do not trust VQE results until the mapping/active-space mismatch is resolved."
        )
    return e_qubit


def _run_single_vqe(
    *,
    active_problem: Any,
    mapper: Any,
    method: str,
    trial: int,
    initial_point: np.ndarray,
    maxiter: int,
    optimizer_name: str,
    seed: int,
    ansatz_reps: int,
    evaluation_budget: int | None = None,
    spsa_a: float | None = None,
    spsa_alpha: float = 0.602,
    spsa_c: float | None = None,
    spsa_gamma: float = 0.101,
    spsa_stability_constant: float = 0.0,
    mapped_hamiltonian: Any = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run one fixed-ansatz VQE trial and retain every objective evaluation."""
    stack = _require_scientific_stack()
    callback_rows: list[dict[str, Any]] = []
    estimator = stack["StatevectorEstimator"]()
    n_orb = int(active_problem.num_spatial_orbitals)
    n_particles = active_problem.num_particles
    hf_state = stack["HartreeFock"](n_orb, n_particles, mapper)
    ansatz_class = {"uccsd": stack["UCCSD"], "puccsd": stack["PUCCSD"]}.get(method)
    if ansatz_class is None:
        raise ValueError(f"unsupported fixed ansatz: {method}")
    ansatz = ansatz_class(
        n_orb,
        n_particles,
        mapper,
        reps=ansatz_reps,
        initial_state=hf_state,
    )

    # Expand parameterized Pauli evolutions once into elementary gates. This
    # avoids repeatedly synthesizing UCC operators during statevector runs and
    # makes the circuit compatible with Qiskit's reverse-mode gradient gates.
    ansatz = stack["transpile"](
        ansatz,
        basis_gates=["x", "rx", "ry", "rz", "cx"],
        optimization_level=0,
    )
    gate_counts = ansatz.count_ops()
    # Keep level-0 logical counts for comparison, but also report a hardware-
    # oriented level-3 compilation. Neither is a device-specific routed count.
    optimized_ansatz = stack["transpile"](
        ansatz,
        basis_gates=["x", "rx", "ry", "rz", "cx"],
        optimization_level=3,
    )
    optimized_gate_counts = optimized_ansatz.count_ops()

    def record(
        eval_count: int, parameters: Any, mean: Any, metadata: dict[str, Any]
    ) -> None:
        # Qiskit Algorithms 0.4 passes estimator metadata as callback argument
        # four (not a standard deviation). StatevectorEstimator is noiseless, so
        # a standard error is not defined and must not be inferred from metadata.
        callback_rows.append(
            {
                "method": method,
                "trial": trial,
                "evaluation": int(eval_count),
                "energy_electronic_hartree": float(np.real(mean)),
                "energy_std": None,
            }
        )

    effective_maxiter = maxiter
    if optimizer_name == "slsqp":
        optimizer = stack["SLSQP"](maxiter=effective_maxiter)
    elif optimizer_name == "lbfgsb":
        optimizer = stack["L_BFGS_B"](
            maxiter=effective_maxiter,
            maxfun=effective_maxiter,
        )
    elif optimizer_name == "cobyla":
        # COBYLA needs an initial simplex of n_parameters + 1 points plus
        # room for an objective evaluation. SciPy otherwise silently raises
        # smaller MAXFUN values to that floor after emitting a warning.
        effective_maxiter = max(maxiter, int(ansatz.num_parameters) + 2)
        optimizer = stack["COBYLA"](maxiter=effective_maxiter, tol=1e-7)
    elif optimizer_name == "powell":
        # Powell's native wrapper has independent iteration and function-call
        # limits; keep both permissive while the shared hard objective budget
        # below enforces the experiment's actual function-call cap.
        optimizer = stack["POWELL"](
            maxiter=effective_maxiter,
            maxfev=effective_maxiter,
            xtol=1e-6,
            tol=1e-8,
        )
    elif optimizer_name == "spsa":
        # SPSA estimates a high-dimensional gradient with two objective
        # evaluations per iteration, independent of the parameter count.
        # Set Qiskit's RNG explicitly because SPSA samples perturbation signs.
        stack["algorithm_globals"].random_seed = seed
        spsa_options: dict[str, Any] = {"maxiter": effective_maxiter}
        if spsa_a is not None or spsa_c is not None:
            if spsa_a is None or spsa_c is None:
                raise ValueError("SPSA schedule requires both --spsa-a and --spsa-c")
            if spsa_a <= 0 or spsa_c <= 0 or spsa_alpha <= 0 or spsa_gamma <= 0:
                raise ValueError("SPSA schedule coefficients and exponents must be positive")
            # Use the standard power-law schedules a_k=a/(A+k+1)^alpha and
            # c_k=c/(k+1)^gamma. Supplying both avoids Qiskit's calibration
            # phase, making objective-call budgets interpretable.
            iterations = np.arange(effective_maxiter, dtype=float)
            rates = spsa_a / (spsa_stability_constant + iterations + 1.0) ** spsa_alpha
            perturbations = spsa_c / (iterations + 1.0) ** spsa_gamma
            spsa_options.update(learning_rate=rates, perturbation=perturbations)
        optimizer = stack["SPSA"](**spsa_options)
    else:
        raise ValueError("optimizer must be slsqp, lbfgsb, cobyla, powell, or spsa")

    # Qiskit's maxiter has optimizer-specific meaning (iterations for SLSQP and
    # SPSA, function evaluations for COBYLA). For controlled experiments we
    # enforce a hard cap on calls to the VQE objective itself. Gradient calls
    # are counted and reported separately below; this is an exact-statevector
    # work budget, not a hardware-shot budget.
    budget_state: dict[str, Any] = {
        "objective_calls": 0,
        "gradient_calls": 0,
        "best_energy": None,
        "best_point": None,
        "budget_hit": False,
    }
    if evaluation_budget is not None:
        if evaluation_budget < 2:
            raise ValueError("--evaluation-budget must be at least 2")
        native_minimize = optimizer.minimize

        class _BudgetReached(Exception):
            pass

        def budgeted_minimize(fun: Any, x0: Any, jac: Any = None, bounds: Any = None) -> Any:
            def counted_fun(point: Any, *args: Any) -> Any:
                # SPSA may batch its +/- perturbation points into a 2-D
                # parameter array. Evaluate rows individually so a remaining
                # budget smaller than a batch is still enforced exactly.
                point_array = np.asarray(point)
                if point_array.ndim > 1:
                    return np.asarray(
                        [counted_fun(row, *args) for row in point_array], dtype=float
                    )
                if budget_state["objective_calls"] >= evaluation_budget:
                    budget_state["budget_hit"] = True
                    raise _BudgetReached
                value = float(np.real(fun(point, *args)))
                budget_state["objective_calls"] += 1
                if budget_state["best_energy"] is None or value < budget_state["best_energy"]:
                    budget_state["best_energy"] = value
                    budget_state["best_point"] = np.asarray(point, dtype=float).copy()
                return value

            def counted_jac(point: Any, *args: Any) -> Any:
                if jac is None:
                    return None
                budget_state["gradient_calls"] += 1
                return jac(point, *args)

            try:
                # Include the common starting state in the hard objective
                # budget and best-so-far tracker. SPSA estimates gradients
                # from perturbed points and may never evaluate x0 itself;
                # without this call, its returned "best" could be worse than
                # the HF reference even though the ansatz starts at HF.
                budget_state["initial_energy"] = float(counted_fun(x0))
                result = native_minimize(
                    counted_fun,
                    x0,
                    jac=counted_jac if jac is not None else None,
                    bounds=bounds,
                )
            except _BudgetReached:
                # Return the best *actually evaluated* state. VQE will then
                # assemble its normal result object, and the separate final
                # verification below checks that state once more.
                result = stack["OptimizerResult"]()
                result.x = np.asarray(budget_state["best_point"], dtype=float)
                result.fun = float(budget_state["best_energy"])
                result.nfev = int(budget_state["objective_calls"])
                result.njev = int(budget_state["gradient_calls"])
                result.nit = None
            if budget_state["best_point"] is not None:
                # For this deterministic statevector benchmark, return the
                # best exact objective value actually sampled within budget.
                # No noisy best-measured-value claim is made here.
                result.x = np.asarray(budget_state["best_point"], dtype=float)
                result.fun = float(budget_state["best_energy"])
            return result

        optimizer.minimize = budgeted_minimize

    vqe = stack["VQE"](
        estimator=estimator,
        ansatz=ansatz,
        optimizer=optimizer,
        initial_point=np.asarray(initial_point, dtype=float),
        gradient=(
            stack["ReverseEstimatorGradient"]()
            if optimizer_name in {"slsqp", "lbfgsb"}
            else None
        ),
        callback=record,
    )
    solver = stack["GroundStateEigensolver"](mapper, vqe)
    started = time.perf_counter()
    result = solver.solve(active_problem)
    elapsed_s = time.perf_counter() - started
    raw = result.raw_result
    total_energy = float(np.real(result.total_energies[0]))
    raw_energy = float(np.real(raw.eigenvalue))
    offset = total_energy - raw_energy
    final_point = np.asarray(raw.optimal_point, dtype=float)
    if mapped_hamiltonian is None:
        raise ValueError("mapped_hamiltonian is required for independent final evaluation")
    verification_job = estimator.run([(ansatz, mapped_hamiltonian, final_point)])
    verified_values = np.asarray(verification_job.result()[0].data.evs).reshape(-1)
    if verified_values.size != 1 or not np.isfinite(verified_values[0]):
        raise RuntimeError("Final exact statevector reevaluation returned an invalid energy")
    verified_electronic = float(np.real(verified_values[0]))
    verified_total = verified_electronic + offset
    recheck_difference = abs(verified_total - total_energy)
    if recheck_difference > 1e-8:
        raise RuntimeError(
            "Fresh exact statevector evaluation disagrees with the VQE-reported "
            f"energy by {recheck_difference:.3e} Ha"
        )
    for row in callback_rows:
        row["energy_total_hartree"] = row["energy_electronic_hartree"] + offset
    optimizer_result = getattr(raw, "optimizer_result", None)
    reported_success = getattr(optimizer_result, "success", None)
    reported_message = getattr(optimizer_result, "message", None)
    optimizer_nit = getattr(optimizer_result, "nit", None)
    optimizer_nfev = getattr(optimizer_result, "nfev", None)
    # Qiskit Algorithms' OptimizerResult does not consistently expose SciPy's
    # success/message fields. Never turn an absent field into a success claim.
    # Also distinguish iteration-based budgets (SLSQP/SPSA) from COBYLA's
    # function-evaluation budget; its `maxiter` option maps to MAXFUN.
    if evaluation_budget is not None:
        budget_reached = bool(
            budget_state["budget_hit"]
            or budget_state["objective_calls"] >= evaluation_budget
        )
        budget_kind = "objective_evaluations"
    elif optimizer_name in {"cobyla", "powell"}:
        budget_reached = (
            None if optimizer_nfev is None else bool(optimizer_nfev >= effective_maxiter)
        )
        budget_kind = "function_evaluations"
    else:
        budget_reached = (
            None if optimizer_nit is None else bool(optimizer_nit >= effective_maxiter)
        )
        budget_kind = "iterations"
    if reported_success is True:
        termination_assessment = "optimizer_reported_success"
    elif reported_success is False:
        termination_assessment = "optimizer_reported_failure"
    elif budget_reached is True:
        termination_assessment = f"{budget_kind}_budget_reached"
    else:
        termination_assessment = "termination_status_not_exposed"
    final_jac = getattr(optimizer_result, "jac", None)
    final_gradient_norm = None
    if final_jac is not None:
        try:
            final_gradient_norm = float(np.linalg.norm(np.asarray(final_jac, dtype=float)))
        except (TypeError, ValueError):
            # Some derivative-free optimizers return a non-numeric placeholder.
            pass
    record_out = {
        "method": method,
        "trial": trial,
        "seed": seed,
        "optimizer": optimizer_name,
        "ansatz_depth": int(ansatz.depth()),
        "ansatz_circuit_size": int(ansatz.size()),
        "ansatz_cx_count": int(gate_counts.get("cx", 0)),
        "transpilation_optimization_level": 0,
        "ansatz_depth_optimization_level_3": int(optimized_ansatz.depth()),
        "ansatz_size_optimization_level_3": int(optimized_ansatz.size()),
        "ansatz_cx_count_optimization_level_3": int(optimized_gate_counts.get("cx", 0)),
        "num_parameters": int(ansatz.num_parameters),
        "ansatz_reps": ansatz_reps,
        "requested_maxiter": maxiter,
        "effective_maxiter": effective_maxiter,
        "requested_objective_evaluation_budget": evaluation_budget,
        # The optimizer objective excludes the constant nuclear/core offset;
        # expose both units of accounting explicitly so starting and final
        # total energies are comparable in saved reports.
        "initial_electronic_energy_hartree": (
            None if evaluation_budget is None else budget_state.get("initial_energy")
        ),
        "initial_energy_hartree": (
            None
            if evaluation_budget is None or budget_state.get("initial_energy") is None
            else float(budget_state["initial_energy"]) + offset
        ),
        "initial_total_energy_hartree": (
            None
            if evaluation_budget is None or budget_state.get("initial_energy") is None
            else float(budget_state["initial_energy"]) + offset
        ),
        "budgeted_objective_evaluations": (
            None if evaluation_budget is None else int(budget_state["objective_calls"])
        ),
        "budgeted_gradient_evaluations": (
            None if evaluation_budget is None else int(budget_state["gradient_calls"])
        ),
        "total_energy_hartree": verified_total,
        "optimizer_reported_total_energy_hartree": total_energy,
        "verified_electronic_energy_hartree": verified_electronic,
        "final_energy_recheck_abs_difference_hartree": recheck_difference,
        "final_validation_energy_evaluations": 1,
        "total_energy_offset_hartree": offset,
        # Count actual estimator calls from the callback. SPSA performs an
        # optional calibration phase that Qiskit's cost_function_evals omits.
        "num_energy_evaluations": len(callback_rows),
        "optimizer_reported_cost_function_evals": getattr(
            raw, "cost_function_evals", None
        ),
        "optimizer_nfev": optimizer_nfev,
        "optimizer_njev": getattr(optimizer_result, "njev", None),
        "optimizer_nit": optimizer_nit,
        "optimizer_status": getattr(optimizer_result, "status", None),
        "optimizer_budget_kind": budget_kind,
        "optimizer_budget_reached": budget_reached,
        "optimizer_termination_assessment": termination_assessment,
        "optimizer_final_gradient_norm": final_gradient_norm,
        "optimizer_result_type": (
            None if optimizer_result is None else type(optimizer_result).__name__
        ),
        "elapsed_seconds": elapsed_s,
        "optimizer_success": (
            None if reported_success is None else bool(reported_success)
        ),
        "optimizer_message": (
            None if reported_message is None else str(reported_message)
        ),
        "spsa_schedule": (
            None
            if optimizer_name != "spsa" or spsa_a is None
            else {
                "a": float(spsa_a),
                "alpha": float(spsa_alpha),
                "c": float(spsa_c),
                "gamma": float(spsa_gamma),
                "stability_constant": float(spsa_stability_constant),
            }
        ),
        "optimal_point": final_point.tolist(),
    }
    return record_out, callback_rows


class _AdaptCycleProgressHandler(logging.Handler):
    """Stream Qiskit's public ADAPT progress logs and checkpoint accepted cycles."""

    fieldnames = [
        "macrocycle",
        "selected_pool_operator",
        "selected_pool_operator_index",
        "max_pool_gradient_abs",
        "energy_electronic_hartree",
        "energy_total_hartree",
        "absolute_error_vs_active_casci_millihartree",
    ]

    def __init__(
        self,
        *,
        max_cycles: int,
        energy_offset: float,
        casci_energy: float,
        checkpoint_path: Path,
        progress_state: dict[str, int],
    ) -> None:
        super().__init__(level=logging.INFO)
        self.max_cycles = int(max_cycles)
        self.energy_offset = float(energy_offset)
        self.casci_energy = float(casci_energy)
        self.checkpoint_path = checkpoint_path
        self.progress_state = progress_state
        self.cycle = 0
        self.selected_operator = ""
        self.selected_index: int | None = None
        self.max_gradient_abs: float | None = None
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        with self.checkpoint_path.open("w", newline="", encoding="utf-8") as stream:
            csv.DictWriter(stream, fieldnames=self.fieldnames).writeheader()

    def emit(self, record: logging.LogRecord) -> None:
        """Convert stable ADAPT info messages into compact, user-facing progress."""
        try:
            message = record.getMessage()
            if message.startswith("--- Iteration #"):
                cycle_text = message.split("#", 1)[1].split("---", 1)[0].strip()
                self.cycle = int(cycle_text)
                self.progress_state["macrocycle"] = self.cycle
                self.selected_operator = ""
                self.selected_index = None
                self.max_gradient_abs = None
                print(
                    f"[ADAPT] starting macrocycle {self.cycle}/{self.max_cycles}: "
                    "evaluating the UCCSD excitation pool",
                    flush=True,
                )
            elif message.startswith("Found maximum gradient "):
                value = message.removeprefix("Found maximum gradient ")
                gradient_text, separator, index_text = value.partition(" at index ")
                if not separator:
                    return
                self.max_gradient_abs = float(gradient_text)
                self.selected_index = int(index_text)
                print(
                    f"[ADAPT] macrocycle {self.cycle}: largest pool gradient="
                    f"{self.max_gradient_abs:.6g} Ha "
                    f"(pool index {self.selected_index})",
                    flush=True,
                )
            elif message.startswith("Adding new operator to the ansatz: "):
                self.selected_operator = message.split(": ", 1)[1]
                print(
                    f"[ADAPT] macrocycle {self.cycle}: selected operator "
                    f"{self.selected_operator}",
                    flush=True,
                )
            elif message.startswith("Current eigenvalue: "):
                electronic_energy = float(
                    np.real(complex(message.split(": ", 1)[1].strip()))
                )
                total_energy = electronic_energy + self.energy_offset
                error_mha = abs(total_energy - self.casci_energy) * HARTREE_TO_MILLIHARTREE
                row = {
                    "macrocycle": self.cycle,
                    "selected_pool_operator": self.selected_operator,
                    "selected_pool_operator_index": self.selected_index,
                    "max_pool_gradient_abs": (
                        None
                        if self.max_gradient_abs is None
                        else self.max_gradient_abs
                    ),
                    "energy_electronic_hartree": electronic_energy,
                    "energy_total_hartree": total_energy,
                    "absolute_error_vs_active_casci_millihartree": error_mha,
                }
                with self.checkpoint_path.open(
                    "a", newline="", encoding="utf-8"
                ) as stream:
                    writer = csv.DictWriter(stream, fieldnames=self.fieldnames)
                    writer.writerow(row)
                    stream.flush()
                print(
                    f"[ADAPT] completed macrocycle {self.cycle}/{self.max_cycles}: "
                    f"E={total_energy:+.9f} Ha; |ΔCASCI|={error_mha:.3f} mHa",
                    flush=True,
                )
            elif "Maximum number of iterations reached" in message:
                print("[ADAPT] stopping: maximum macrocycle count reached", flush=True)
            elif "terminated successfully" in message or "Alternating sequence found" in message:
                print(f"[ADAPT] {message}", flush=True)
        except Exception:
            self.handleError(record)


def _run_adapt(
    *,
    active_problem: Any,
    mapper: Any,
    maxiter: int,
    max_cycles: int,
    optimizer_name: str,
    seed: int,
    casci_energy: float,
    output_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run Qiskit Algorithms ADAPT-VQE with Qiskit Nature's UCCSD pool."""
    stack = _require_scientific_stack()
    n_orb = int(active_problem.num_spatial_orbitals)
    n_particles = active_problem.num_particles
    hf_state = stack["HartreeFock"](n_orb, n_particles, mapper)
    pool_ansatz = stack["UCCSD"](
        n_orb,
        n_particles,
        mapper,
        initial_state=hf_state,
    )
    # AdaptVQE reuses and mutates the original EvolvedOperatorAnsatz to hold
    # the selected operators, so capture the full pool size before solving.
    operator_pool_size = len(pool_ansatz.operators)
    if optimizer_name == "slsqp":
        optimizer = stack["SLSQP"](maxiter=maxiter)
    elif optimizer_name == "lbfgsb":
        optimizer = stack["L_BFGS_B"](maxiter=maxiter, maxfun=maxiter)
    elif optimizer_name == "cobyla":
        optimizer = stack["COBYLA"](maxiter=maxiter, tol=1e-7)
    elif optimizer_name == "powell":
        optimizer = stack["POWELL"](
            maxiter=maxiter, maxfev=maxiter, xtol=1e-6, tol=1e-8
        )
    elif optimizer_name == "spsa":
        stack["algorithm_globals"].random_seed = seed
        optimizer = stack["SPSA"](maxiter=maxiter)
    else:
        raise ValueError("optimizer must be slsqp, lbfgsb, cobyla, powell, or spsa")
    # The VQE callback exposes objective evaluations inside every ADAPT
    # macrocycle. Keep a flushed CSV checkpoint so users can see progress and
    # recover completed energy evaluations even if a later cycle is stopped.
    optimizer_history_path = output_dir / "adapt_optimizer_history.csv"
    optimizer_fields = [
        "macrocycle",
        "optimizer_evaluation",
        "energy_electronic_hartree",
        "energy_total_hartree",
        "absolute_error_vs_active_casci_millihartree",
        "parameter_count",
    ]
    with optimizer_history_path.open("w", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, fieldnames=optimizer_fields).writeheader()

    active_constants = getattr(active_problem.hamiltonian, "constants", {}) or {}
    progress_offset = float(
        np.real(sum(complex(value) for value in active_constants.values()))
    )
    progress_state = {"macrocycle": 0}
    optimizer_evaluations = 0

    def record_optimizer_evaluation(
        eval_count: int, parameters: Any, mean: Any, metadata: dict[str, Any]
    ) -> None:
        nonlocal optimizer_evaluations
        electronic_energy = float(np.real(np.asarray(mean).item()))
        total_energy = electronic_energy + progress_offset
        row = {
            "macrocycle": int(progress_state["macrocycle"]),
            "optimizer_evaluation": int(eval_count),
            "energy_electronic_hartree": electronic_energy,
            "energy_total_hartree": total_energy,
            "absolute_error_vs_active_casci_millihartree": abs(
                total_energy - casci_energy
            )
            * HARTREE_TO_MILLIHARTREE,
            "parameter_count": int(np.asarray(parameters).size),
        }
        optimizer_evaluations += 1
        with optimizer_history_path.open("a", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=optimizer_fields)
            writer.writerow(row)
            stream.flush()
        print(
            f"[ADAPT cycle {row['macrocycle']}] VQE eval {eval_count}: "
            f"E={total_energy:+.9f} Ha; "
            f"|ΔCASCI|={row['absolute_error_vs_active_casci_millihartree']:.3f} mHa",
            flush=True,
        )

    vqe = stack["VQE"](
        estimator=stack["StatevectorEstimator"](),
        ansatz=pool_ansatz,
        optimizer=optimizer,
        initial_point=np.zeros(pool_ansatz.num_parameters, dtype=float),
        # Use exact reverse-mode statevector gradients for gradient-based
        # inner optimizers; this avoids finite-difference perturbations per
        # active parameter. This is ideal-simulator gradient information,
        # not a hardware gradient or shot-cost estimate.
        gradient=(
            stack["ReverseEstimatorGradient"]()
            if optimizer_name in {"slsqp", "lbfgsb"}
            else None
        ),

        callback=record_optimizer_evaluation,
    )
    adapt = stack["AdaptVQE"](
        vqe,
        gradient_threshold=1e-4,
        eigenvalue_threshold=1e-8,
        max_iterations=max_cycles,
    )
    # Qiskit Nature 0.8's documented ADAPT-VQE integration expects auxiliary
    # operator support from AdaptVQE; this shim follows its official how-to.
    adapt.supports_aux_operators = lambda: True
    solver = stack["GroundStateEigensolver"](mapper, adapt)

    # Qiskit's public ADAPT implementation logs the chosen pool gradient and
    # the energy at every completed macrocycle. Relay only that logger to the
    # terminal and persist accepted cycles immediately; this avoids replacing
    # the library algorithm with a fragile private reimplementation.
    adapt_logger = logging.getLogger(
        "qiskit_algorithms.minimum_eigensolvers.adapt_vqe"
    )
    previous_level = adapt_logger.level
    previous_propagate = adapt_logger.propagate
    handler = _AdaptCycleProgressHandler(
        max_cycles=max_cycles,
        energy_offset=progress_offset,
        casci_energy=casci_energy,
        checkpoint_path=output_dir / "adapt_progress.csv",
        progress_state=progress_state,
    )
    adapt_logger.addHandler(handler)
    adapt_logger.setLevel(logging.INFO)
    adapt_logger.propagate = False
    started = time.perf_counter()
    try:
        result = solver.solve(active_problem)
    finally:
        adapt_logger.removeHandler(handler)
        adapt_logger.setLevel(previous_level)
        adapt_logger.propagate = previous_propagate
    elapsed_s = time.perf_counter() - started
    raw = result.raw_result
    total_energy = float(np.real(result.total_energies[0]))
    raw_energy = float(np.real(raw.eigenvalue))
    offset = total_energy - raw_energy
    offset_difference = abs(offset - progress_offset)
    if offset_difference > 1e-7:
        raise RuntimeError(
            "ADAPT progress-energy offset disagrees with the final Qiskit result: "
            f"{progress_offset:.12f} vs {offset:.12f} Ha"
        )
    # Count the final adaptive circuit using the same basis and transpilation
    # levels as the fixed UCCSD/PUCCSD runs, enabling a real accuracy/resource
    # comparison instead of reporting parameter count alone.
    basis_gates = ["x", "rx", "ry", "rz", "cx"]
    resource_started = time.perf_counter()
    logical_circuit = stack["transpile"](
        raw.optimal_circuit, basis_gates=basis_gates, optimization_level=0
    )
    logical_counts = logical_circuit.count_ops()
    optimized_circuit = stack["transpile"](
        logical_circuit, basis_gates=basis_gates, optimization_level=3
    )
    optimized_counts = optimized_circuit.count_ops()
    resource_transpilation_s = time.perf_counter() - resource_started
    history = [float(np.real(value)) + offset for value in raw.eigenvalue_history]
    rows = [
        {
            "method": "adapt_vqe",
            "trial": 0,
            "macrocycle": cycle,
            "energy_total_hartree": energy,
        }
        for cycle, energy in enumerate(history, start=1)
    ]
    summary = {
        "method": "adapt_vqe",
        "trial": 0,
        "optimizer": optimizer_name,
        # GroundStateEigensolver wraps the AdaptVQEResult in
        # ElectronicStructureResult; ADAPT-specific fields live on raw_result.
        "num_parameters": int(raw.optimal_circuit.num_parameters),
        "ansatz_depth": int(logical_circuit.depth()),
        "ansatz_circuit_size": int(logical_circuit.size()),
        "ansatz_cx_count": int(logical_counts.get("cx", 0)),
        "transpilation_optimization_level": 0,
        "ansatz_depth_optimization_level_3": int(optimized_circuit.depth()),
        "ansatz_size_optimization_level_3": int(optimized_circuit.size()),
        "ansatz_cx_count_optimization_level_3": int(optimized_counts.get("cx", 0)),
        "resource_transpilation_seconds": resource_transpilation_s,
        "optimal_point": np.asarray(raw.optimal_point, dtype=float).tolist(),
        "operator_pool_size": int(operator_pool_size),
        "macrocycles": int(raw.num_iterations),
        "final_max_gradient": float(np.real(raw.final_max_gradient)),
        "final_max_gradient_abs": abs(float(np.real(raw.final_max_gradient))),
        "termination_criterion": str(raw.termination_criterion),
        "total_energy_hartree": total_energy,
        "total_energy_offset_hartree": offset,
        "num_energy_evaluations": int(optimizer_evaluations),
        "inner_optimizer_gradient": (
            "reverse_mode_statevector"
            if optimizer_name in {"slsqp", "lbfgsb"}
            else None
        ),
        "last_macrocycle_optimizer_gradient_evaluations": getattr(
            getattr(raw, "optimizer_result", None), "njev", None
        ),
        "last_macrocycle_optimizer_evaluations": int(
            getattr(raw, "cost_function_evals", 0)
        ),
        "adapt_progress_csv": str(output_dir / "adapt_progress.csv"),
        "adapt_optimizer_history_csv": str(optimizer_history_path),
        "elapsed_seconds": elapsed_s,
    }
    return summary, rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def _write_plot(path: Path, exact_energy: float, history_rows: list[dict[str, Any]]) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib missing; skipped convergence plot", file=sys.stderr)
        return
    groups: dict[str, list[float]] = {}
    for row in history_rows:
        if "energy_total_hartree" not in row:
            continue
        # Keep trials separate; joining their traces would create a fake
        # convergence line across unrelated optimizer restarts.
        label = f"{row['method']} trial {row.get('trial', 0)}"
        groups.setdefault(label, []).append(
            HARTREE_TO_MILLIHARTREE
            * (float(row["energy_total_hartree"]) - exact_energy)
        )
    fig, ax = plt.subplots(figsize=(9, 5.5), constrained_layout=True)
    for method, values in groups.items():
        ax.plot(np.arange(1, len(values) + 1), values, marker=".", label=method)
    ax.axhline(0.0, color="black", linewidth=1, label="CASCI reference")
    ax.axhline(
        HARTREE_TO_MILLIHARTREE * CHEMICAL_ACCURACY_HA,
        color="crimson",
        linestyle="--",
        linewidth=1,
        label="1.6 mHa threshold",
    )
    ax.set_xlabel("Recorded optimizer evaluation / ADAPT macrocycle")
    ax.set_ylabel("Energy above active-space CASCI (mHa)")
    ax.set_title("H₂O asymmetric O–H extension: ideal statevector VQE")
    ax.set_ylim(bottom=min(-0.2, ax.get_ylim()[0]))
    ax.grid(alpha=0.25)
    ax.legend()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def run(args: argparse.Namespace) -> Path:
    geometry = Geometry(args.fixed_oh, args.stretched_oh, args.angle)
    geometry.validate()
    atom = geometry.pyscf_atom_spec()
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Geometry (Å, angle degrees): {atom}; H-O-H={geometry.hoh_angle_deg:.6f}")
    print("Computing RHF, all-electron STO-3G FCI, and frozen-core CAS(8e,6o) CASCI...")
    refs = calculate_references(atom)
    active_problem, mapper, mapped_hamiltonian, mapper_info = build_active_problem(atom)
    q_exact = verify_qubit_exact(
        active_problem, mapper, refs["frozen_core_casci_hartree"]
    )
    refs["mapped_qubit_exact_hartree"] = q_exact
    refs["mapped_qubit_exact_abs_difference_from_casci_hartree"] = abs(
        q_exact - refs["frozen_core_casci_hartree"]
    )
    print(f"RHF                {refs['rhf_hartree']:.12f} Ha")
    print(f"Frozen-core CASCI  {refs['frozen_core_casci_hartree']:.12f} Ha")
    print(f"Full STO-3G FCI    {refs['full_sto3g_fci_hartree']:.12f} Ha")
    print(f"Mapped exact check {q_exact:.12f} Ha (independently agrees with CASCI)")

    metadata = {
        "model": "H2O, asymmetric single O-H extension; STO-3G",
        "geometry": asdict(geometry),
        "atom_spec_angstrom": atom,
        "active_space": "CAS(8e,6o), closed-shell (4 alpha, 4 beta), lowest inactive MO frozen",
        "active_space_is_approximation_to_full_sto3g": True,
        "measurement_model": "exact statevector expectation values; no noise or finite shots",
        "chemical_accuracy_threshold_hartree": CHEMICAL_ACCURACY_HA,
        "references": refs,
        "mapping": mapper_info,
        "software": {
            "python": sys.version,
            "platform": platform.platform(),
            "numpy": np.__version__,
            "scipy": __import__("scipy").__version__,
            "pyscf": __import__("pyscf").__version__,
            "qiskit": __import__("qiskit").__version__,
            "qiskit_nature": __import__("qiskit_nature").__version__,
            "qiskit_algorithms": __import__("qiskit_algorithms").__version__,
        },
    }
    (output_dir / "reference.json").write_text(
        json.dumps(metadata, indent=2, default=_json_default), encoding="utf-8"
    )

    summary_rows: list[dict[str, Any]] = []
    history_rows: list[dict[str, Any]] = []
    if not args.reference_only:
        methods = [x.strip().lower() for x in args.methods.split(",") if x.strip()]
        allowed = {"uccsd", "puccsd", "adapt"}
        unknown = set(methods) - allowed
        if unknown:
            raise ValueError(f"unknown methods: {sorted(unknown)}; choose from {sorted(allowed)}")
        if not methods:
            raise ValueError("select at least one VQE method, or use --reference-only")
        if args.random_restarts_only and "adapt" in methods:
            raise ValueError(
                "--random-restarts-only applies to fixed ansätze (UCCSD/PUCCSD), "
                "not ADAPT-VQE"
            )
        for method in methods:
            if method == "adapt":
                record, rows = _run_adapt(
                    active_problem=active_problem,
                    mapper=mapper,
                    maxiter=args.maxiter,
                    max_cycles=args.adapt_cycles,
                    optimizer_name=args.optimizer,
                    seed=args.seed,
                    casci_energy=refs["frozen_core_casci_hartree"],
                    output_dir=output_dir,
                )
                summary_rows.append(record)
                history_rows.extend(rows)
                continue

            # A restart-only run starts at trial 1, preserving the same seeded
            # initialization convention while avoiding an expensive repeat of
            # the already-recorded deterministic Hartree-Fock-start trial 0.
            trial_indices = (
                range(1, args.restarts + 1)
                if args.random_restarts_only
                else range(args.restarts)
            )
            for trial in trial_indices:
                seed = args.seed + trial
                rng = np.random.default_rng(seed)
                # A zero point is included as a deterministic HF-start check.
                # Later restarts perturb around HF rather than claiming random
                # initializations are intrinsically fair across different ansätze.
                stack = _require_scientific_stack()
                ansatz_class = {
                    "uccsd": stack["UCCSD"],
                    "puccsd": stack["PUCCSD"],
                }[method]
                hf_state = stack["HartreeFock"](
                    active_problem.num_spatial_orbitals,
                    active_problem.num_particles,
                    mapper,
                )
                ansatz = ansatz_class(
                    active_problem.num_spatial_orbitals,
                    active_problem.num_particles,
                    mapper,
                    reps=args.ansatz_reps,
                    initial_state=hf_state,
                )
                warm_points = getattr(args, "_warm_start_points", {})
                if trial == 0 and method in warm_points:
                    initial_point = np.asarray(warm_points[method], dtype=float)
                    if initial_point.shape != (ansatz.num_parameters,):
                        raise ValueError(
                            f"warm-start vector for {method} has shape {initial_point.shape}, "
                            f"expected {(ansatz.num_parameters,)}"
                        )
                elif trial == 0:
                    initial_point = np.zeros(ansatz.num_parameters, dtype=float)
                else:
                    # Use broad but bounded perturbations so restarts can probe
                    # distinct basins. A tiny 0.05-rad Gaussian mostly repeats
                    # the same HF basin and is not a meaningful basin search.
                    initial_point = rng.uniform(
                        -args.restart_scale,
                        args.restart_scale,
                        size=ansatz.num_parameters,
                    )
                record, rows = _run_single_vqe(
                    active_problem=active_problem,
                    mapper=mapper,
                    method=method,
                    trial=trial,
                    initial_point=initial_point,
                    maxiter=args.maxiter,
                    optimizer_name=args.optimizer,
                    seed=seed,
                    ansatz_reps=args.ansatz_reps,
                    evaluation_budget=args.evaluation_budget,
                    spsa_a=args.spsa_a,
                    spsa_alpha=args.spsa_alpha,
                    spsa_c=args.spsa_c,
                    spsa_gamma=args.spsa_gamma,
                    spsa_stability_constant=args.spsa_stability_constant,
                    mapped_hamiltonian=mapped_hamiltonian,
                )
                record["absolute_error_vs_active_casci_hartree"] = abs(
                    record["total_energy_hartree"] - refs["frozen_core_casci_hartree"]
                )
                variational_defect = (
                    refs["frozen_core_casci_hartree"] - record["total_energy_hartree"]
                )
                record["variational_bound_check"] = (
                    "pass" if variational_defect <= 1e-7 else "fail"
                )
                if variational_defect > 1e-7:
                    raise RuntimeError(
                        f"{method} energy is {variational_defect:.3e} Ha below the "
                        "active-space CASCI ground energy; check Hamiltonian offsets, "
                        "mapping, or reference consistency before trusting this result"
                    )
                record["within_chemical_accuracy_of_active_casci"] = (
                    record["absolute_error_vs_active_casci_hartree"]
                    <= CHEMICAL_ACCURACY_HA
                )
                record["initialization"] = (
                    "warm-start from preceding geometry"
                    if trial == 0 and method in warm_points
                    else ("Hartree-Fock zero-amplitude" if trial == 0 else "seeded uniform perturbation")
                )
                record["restart_scale_radians"] = (
                    None if trial == 0 else args.restart_scale
                )
                summary_rows.append(record)
                history_rows.extend(rows)
                print(
                    f"{method:8s} trial={trial} energy={record['total_energy_hartree']:.12f} Ha "
                    f"|ΔCASCI|={record['absolute_error_vs_active_casci_hartree'] * 1000:.3f} mHa "
                    f"evals={record['num_energy_evaluations']}"
                )

        # ADAPT has a different result structure; compute its error after total
        # energy interpretation and attach the same criterion as other methods.
        for record in summary_rows:
            if record["method"] == "adapt_vqe":
                error = abs(record["total_energy_hartree"] - refs["frozen_core_casci_hartree"])
                record["absolute_error_vs_active_casci_hartree"] = error
                record["within_chemical_accuracy_of_active_casci"] = error <= CHEMICAL_ACCURACY_HA
                variational_defect = (
                    refs["frozen_core_casci_hartree"] - record["total_energy_hartree"]
                )
                record["variational_bound_check"] = (
                    "pass" if variational_defect <= 1e-7 else "fail"
                )
                if variational_defect > 1e-7:
                    raise RuntimeError(
                        f"ADAPT-VQE energy is {variational_defect:.3e} Ha below the "
                        "active-space CASCI ground energy; check Hamiltonian offsets, "
                        "mapping, or reference consistency before trusting this result"
                    )
                print(
                    "ADAPT final: "
                    f"E={record['total_energy_hartree']:+.9f} Ha; "
                    f"|ΔCASCI|={error * HARTREE_TO_MILLIHARTREE:.3f} mHa; "
                    f"cycles={record['macrocycles']}; "
                    f"parameters={record['num_parameters']}; "
                    f"|max pool gradient|={record['final_max_gradient_abs']:.6g} Ha; "
                    f"stop={record['termination_criterion']}; "
                    f"optimizer objective evaluations={record['num_energy_evaluations']}; "
                    f"elapsed={record['elapsed_seconds']:.1f}s",
                    flush=True,
                )

    _write_csv(
        output_dir / "vqe_summary.csv",
        [
            {key: value for key, value in row.items() if key != "optimal_point"}
            for row in summary_rows
        ],
    )
    _write_csv(output_dir / "optimization_history.csv", history_rows)
    if history_rows:
        _write_plot(
            output_dir / "convergence.png",
            refs["frozen_core_casci_hartree"],
            history_rows,
        )

    run_summary = {
        "reference": refs,
        "mapping": mapper_info,
        "vqe_runs": summary_rows,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(run_summary, indent=2, default=_json_default), encoding="utf-8"
    )
    print(f"Saved reproducible outputs to: {output_dir}")
    return output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixed-oh", type=float, default=DEFAULT_RHF_BOND_ANGSTROM)
    parser.add_argument("--stretched-oh", type=float, default=DEFAULT_STRETCHED_BOND_ANGSTROM)
    parser.add_argument("--angle", type=float, default=DEFAULT_ANGLE_DEG)
    parser.add_argument(
        "--scan-r2",
        help="comma-separated stretched O-H distances in Å",
    )
    parser.add_argument(
        "--warm-start-scan",
        action="store_true",
        help="initialize each fixed-ansatz geometry from the preceding optimized point",
    )
    parser.add_argument("--output", default="results/references/asymmetric-r2.20")
    parser.add_argument("--reference-only", action="store_true")
    parser.add_argument(
        "--methods",
        default="uccsd,adapt",
        help="comma-separated fixed/adaptive ansätze: uccsd, puccsd, adapt",
    )
    parser.add_argument("--restarts", type=int, default=2)
    parser.add_argument(
        "--random-restarts-only",
        action="store_true",
        help=(
            "run seeded non-Hartree-Fock starts only (trial indices begin at 1); "
            "useful for extending an existing HF-start result without repeating it"
        ),
    )
    parser.add_argument(
        "--restart-scale", type=float, default=0.5,
        help="half-width in radians of seeded uniform non-HF restart amplitudes",
    )
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument(
        "--optimizer",
        choices=("slsqp", "lbfgsb", "cobyla", "powell", "spsa"),
        default="slsqp",
    )
    parser.add_argument("--maxiter", type=int, default=120)
    parser.add_argument(
        "--evaluation-budget",
        type=int,
        help=(
            "hard cap on VQE objective evaluations for fixed-ansatz runs; "
            "gradient evaluations are reported separately, and final exact "
            "reevaluation is outside this optimization budget"
        ),
    )
    parser.add_argument(
        "--spsa-a", type=float,
        help="SPSA learning-rate coefficient a; set together with --spsa-c",
    )
    parser.add_argument("--spsa-alpha", type=float, default=0.602)
    parser.add_argument(
        "--spsa-c", type=float,
        help="SPSA perturbation coefficient c; set together with --spsa-a",
    )
    parser.add_argument("--spsa-gamma", type=float, default=0.101)
    parser.add_argument("--spsa-stability-constant", type=float, default=0.0)
    parser.add_argument("--adapt-cycles", type=int, default=30)
    parser.add_argument(
        "--ansatz-reps", type=int, default=1,
        help="UCCSD/PUCCSD repetitions; use 1 for the current baseline",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.restarts < 1:
        parser.error("--restarts must be at least one")
    if args.restart_scale <= 0 or not np.isfinite(args.restart_scale):
        parser.error("--restart-scale must be a finite positive number")
    if args.maxiter < 1 or args.adapt_cycles < 1:
        parser.error("--maxiter and --adapt-cycles must be positive")
    if args.evaluation_budget is not None and args.evaluation_budget < 2:
        parser.error("--evaluation-budget must be at least 2")
    if (args.spsa_a is None) != (args.spsa_c is None):
        parser.error("--spsa-a and --spsa-c must be supplied together")
    spsa_values = [args.spsa_alpha, args.spsa_gamma, args.spsa_stability_constant]
    spsa_values.extend(x for x in (args.spsa_a, args.spsa_c) if x is not None)
    if not all(np.isfinite(x) for x in spsa_values):
        parser.error("SPSA schedule values must be finite")
    if args.spsa_alpha <= 0 or args.spsa_gamma <= 0:
        parser.error("SPSA alpha and gamma must be positive")
    if args.spsa_stability_constant < 0:
        parser.error("--spsa-stability-constant cannot be negative")
    if args.optimizer != "spsa" and args.spsa_a is not None:
        parser.error("SPSA schedule options require --optimizer spsa")
    if args.evaluation_budget is not None and any(
        method.strip().lower() == "adapt" for method in args.methods.split(",")
    ):
        parser.error("--evaluation-budget currently applies only to fixed ansätze")
    if args.ansatz_reps < 1:
        parser.error("--ansatz-reps must be at least one")
    if args.random_restarts_only and args.scan_r2:
        parser.error("--random-restarts-only is for a single geometry, not a scan")
    try:
        if not args.scan_r2:
            run(args)
        else:
            try:
                distances = [float(value.strip()) for value in args.scan_r2.split(",") if value.strip()]
            except ValueError as exc:
                parser.error(f"invalid --scan-r2 value: {exc}")
            if not distances or len(set(distances)) != len(distances):
                parser.error("--scan-r2 must contain unique comma-separated distances")
            if args.warm_start_scan:
                # A continuation scan is most meaningful when adjacent points
                # are close in geometry; sort rather than honoring accidental order.
                distances.sort()
            base = Path(args.output).expanduser().resolve()
            base.mkdir(parents=True, exist_ok=True)
            aggregate: list[dict[str, Any]] = []
            warm_start_points: dict[str, list[float]] = {}
            for distance in distances:
                child = argparse.Namespace(**vars(args))
                child.stretched_oh = distance
                child.output = str(base / f"r2-{distance:.3f}")
                child.scan_r2 = None
                child._warm_start_points = dict(warm_start_points)
                run(child)
                data = json.loads(
                    (Path(child.output) / "summary.json").read_text(encoding="utf-8")
                )
                reference = data["reference"]
                if args.warm_start_scan:
                    # ADAPT's operator sequence can change with geometry; only
                    # fixed UCCSD/PUCCSD parameter vectors are transferred.
                    warm_start_points = {
                        item["method"]: item["optimal_point"]
                        for item in data.get("vqe_runs", [])
                        if item.get("method") in {"uccsd", "puccsd"}
                        and item.get("optimal_point") is not None
                    }
                aggregate.append(
                    {
                        "record_type": "reference",
                        "fixed_oh_angstrom": child.fixed_oh,
                        "stretched_oh_angstrom": distance,
                        "angle_deg": child.angle,
                        "rhf_hartree": reference["rhf_hartree"],
                        "rhf_internal_stable": reference["rhf_internal_stable"],
                        "rhf_external_stable": reference["rhf_external_stable"],
                        "frozen_core_casci_hartree": reference["frozen_core_casci_hartree"],
                        "full_sto3g_fci_hartree": reference["full_sto3g_fci_hartree"],
                        "active_space_bias_hartree": reference[
                            "active_space_bias_vs_full_fci_hartree"
                        ],
                    }
                )
                for item in data["vqe_runs"]:
                    aggregate.append(
                        {
                            "record_type": "vqe",
                            "fixed_oh_angstrom": child.fixed_oh,
                            "stretched_oh_angstrom": distance,
                            "angle_deg": child.angle,
                            **item,
                        }
                    )
            _write_csv(base / "asymmetric_stretch_scan.csv", aggregate)
            (base / "asymmetric_stretch_scan.json").write_text(
                    json.dumps(aggregate, indent=2, default=_json_default), encoding="utf-8"
            )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
