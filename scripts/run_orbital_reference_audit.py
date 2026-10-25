#!/usr/bin/env python3
"""Audit the RHF-orbital CASCI reference against orbital-optimized CASSCF.

The current VQE Hamiltonian uses CAS(8e,6o) integrals in RHF orbitals. This
script checks whether orbital relaxation materially changes that reference,
especially at the stretched asymmetric geometries where RHF may be externally
unstable. A CASSCF energy is a different Hamiltonian/orbital construction; do
not score the existing VQE against it unless the VQE integrals are rebuilt in
the same optimized orbitals.

Example (WSL, from this project directory):
    python scripts/run_orbital_reference_audit.py --scan-r2 1.8,2.2,2.6
"""

from __future__ import annotations
# INSTALL COMMAND (Quanta VQE)
# From the repository root, install dependencies with:
# python -m pip install --prefer-binary -r config/requirements/requirements-wsl.txt


import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
from pyscf import gto, mcscf, scf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from h2o_vqe.engine import Geometry


def parse_scan(value: str) -> tuple[float, ...]:
    try:
        values = tuple(float(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--scan-r2 must be comma-separated distances") from exc
    if not values or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("provide a nonempty list of unique distances")
    if any(not math.isfinite(r) or not 0.3 <= r <= 8.0 for r in values):
        raise argparse.ArgumentTypeError("each stretched O-H distance must be in [0.3, 8.0] Å")
    return values


def audit_one(fixed_oh: float, stretched_oh: float, angle: float) -> dict[str, Any]:
    geometry = Geometry(fixed_oh, stretched_oh, angle)
    atom = geometry.pyscf_atom_spec()
    mol = gto.M(
        atom=atom,
        unit="Angstrom",
        basis="sto-3g",
        charge=0,
        spin=0,
        symmetry=False,
        verbose=0,
    )
    rhf = scf.RHF(mol)
    rhf.conv_tol = 1e-11
    rhf.max_cycle = 200
    e_rhf = float(rhf.kernel())
    if not rhf.converged:
        rhf = rhf.newton()
        rhf.conv_tol = 1e-10
        rhf.max_cycle = 200
        e_rhf = float(rhf.kernel())
    if not rhf.converged:
        raise RuntimeError(f"RHF did not converge at stretched O-H={stretched_oh:g} Å")

    # PySCF returns (internal orbitals, external orbitals, internal stable,
    # external stable) when return_status=True.
    _, _, stable_internal, stable_external = rhf.stability(
        internal=True, external=True, return_status=True
    )

    casci = mcscf.CASCI(rhf, 6, (4, 4))
    casci.conv_tol = 1e-10
    e_casci = float(casci.kernel()[0])
    if casci.ci is None or not math.isfinite(e_casci):
        raise RuntimeError(f"CASCI did not produce a valid root at R={stretched_oh:g} Å")
    casci_rdm1 = casci.fcisolver.make_rdm1(casci.ci, casci.ncas, casci.nelecas)
    casci_noons = np.linalg.eigvalsh(np.asarray(casci_rdm1))[::-1]

    casscf = mcscf.CASSCF(rhf, 6, (4, 4))
    casscf.conv_tol = 1e-10
    casscf.conv_tol_grad = 1e-6
    casscf.max_cycle_macro = 100
    e_casscf = float(casscf.kernel()[0])
    casscf_converged = bool(casscf.converged)
    if casscf.ci is None or not math.isfinite(e_casscf):
        raise RuntimeError(f"CASSCF did not produce a valid root at R={stretched_oh:g} Å")
    casscf_rdm1 = casscf.fcisolver.make_rdm1(
        casscf.ci, casscf.ncas, casscf.nelecas
    )
    casscf_noons = np.linalg.eigvalsh(np.asarray(casscf_rdm1))[::-1]

    return {
        "fixed_oh_angstrom": fixed_oh,
        "stretched_oh_angstrom": stretched_oh,
        "hoh_angle_deg": angle,
        "atom_spec_angstrom": atom,
        "rhf_hartree": e_rhf,
        "rhf_converged": bool(rhf.converged),
        "rhf_internal_stable": None if stable_internal is None else bool(stable_internal),
        "rhf_external_stable": None if stable_external is None else bool(stable_external),
        "casci_8e6o_rhf_orbitals_hartree": e_casci,
        "casscf_8e6o_orbital_optimized_hartree": e_casscf,
        "casscf_converged": casscf_converged,
        "casscf_macro_iterations": int(getattr(casscf, "cycles", 0)),
        "casscf_minus_casci_mha": 1000.0 * (e_casscf - e_casci),
        "casci_active_natural_occupations": [float(x) for x in casci_noons],
        "casscf_active_natural_occupations": [float(x) for x in casscf_noons],
        "interpretation": (
            "CASSCF and CASCI values use different orbital optimization; an existing VQE "
            "CASCI Hamiltonian must not be compared directly to the CASSCF number."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixed-oh", type=float, default=0.96)
    parser.add_argument("--scan-r2", type=parse_scan, default=(1.8, 2.2, 2.6))
    parser.add_argument("--angle", type=float, default=104.5)
    parser.add_argument("--output", type=Path, default=Path("results/references/orbital-reference-audit"))
    args = parser.parse_args()
    if not math.isfinite(args.fixed_oh) or not 0.3 <= args.fixed_oh <= 3.5:
        parser.error("--fixed-oh must be finite and in [0.3, 3.5] Å")
    if not math.isfinite(args.angle) or not 20.0 <= args.angle <= 170.0:
        parser.error("--angle must be finite and in [20, 170] degrees")

    rows = [audit_one(args.fixed_oh, r2, args.angle) for r2 in args.scan_r2]
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "orbital_reference_audit.json"
    csv_path = output / "orbital_reference_audit.csv"
    json_path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    # Natural-occupation vectors are retained in JSON; CSV remains a compact
    # numerical comparison useful for plotting the energies and stability flags.
    compact_rows = [
        {key: value for key, value in row.items()
         if key not in {"atom_spec_angstrom", "interpretation",
                        "casci_active_natural_occupations",
                        "casscf_active_natural_occupations"}}
        for row in rows
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(compact_rows[0]))
        writer.writeheader()
        writer.writerows(compact_rows)
    for row in rows:
        stability = "stable" if row["rhf_external_stable"] else "externally unstable"
        print(
            f"R={row['stretched_oh_angstrom']:.3f} Å: RHF {stability}; "
            f"CASCI={row['casci_8e6o_rhf_orbitals_hartree']:.10f} Ha; "
            f"CASSCF={row['casscf_8e6o_orbital_optimized_hartree']:.10f} Ha; "
            f"Δ(CASSCF−CASCI)={row['casscf_minus_casci_mha']:.3f} mHa; "
            f"CASSCF converged={row['casscf_converged']}"
        )
    print(f"Saved {json_path}")
    print(f"Saved {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
