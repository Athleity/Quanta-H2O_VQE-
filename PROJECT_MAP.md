# Project map

## Maintained implementation

- `src/h2o_vqe/engine.py` — geometry, PySCF reference chain, active-space Hamiltonian, mapping verification, UCCSD/PUCCSD VQE, and fermionic ADAPT-VQE.
- `src/h2o_vqe/noise.py` — synthetic finite-shot fixed-parameter Aer evaluation.
- `src/h2o_vqe/fast_noise.py` — faster approximate noisy-statevector demonstration; its assumptions are described in the module and its outputs must be labeled as a model.
- `src/h2o_vqe/backend_noise.py` — finite-shot Aer simulation initialized from an IBM backend calibration snapshot; it does not submit QPU jobs.
- `src/h2o_vqe/ibm_qpu.py` — dry-run-first IBM Runtime measurement of a saved circuit and parameters; QPU submission requires explicit `--submit`.

## Entry points and workflows

- `h2o_vqe.py`, `noisy_energy.py` — compatibility launchers; scientific code stays in `src/h2o_vqe/`.
- `scripts/run_optimizer_study.py` — SPSA tuning plus held-out optimizer comparison.
- `scripts/run_ansatz_resource_study.py` — fixed-budget ansatz and circuit resource comparison.
- `scripts/run_orbital_reference_audit.py` — RHF stability and CASCI/CASSCF scan.
- `scripts/make_publication_figures.py` — regenerates figure assets from archived results.
- `scripts/run_noise_ansatz_study.sh`, `scripts/run_backend_calibrated_noise.sh`, `scripts/run_fast_noisy_simulation.py` — explicit noise workflows with separate evidence labels.
- `notebooks/h2o_asymmetric_stretch.ipynb` — Colab/Jupyter end-to-end demonstration; package install appears in the first code cell.

## Documentation and outputs

- `README.md` — project, installation, workflow, results, and scope.
- `docs/RESEARCH.md` — literature and source review; root `RESEARCH.md` points to it.
- `docs/PROJECT_STATUS.md` — dated results snapshot, not live run monitoring.
- `results/references/`, `ansatz/`, `scans/`, `optimizers/` — reproducible scientific outputs.
- `results/noisy-demo/` — one deliberately low-shot synthetic noise example, with uncertainty.
- `results/publication_figures/` — editable SVGs, high-resolution PNGs, manifest, catalog, and gallery.
- `results/hardware/` — reserved for completed, auditable IBM QPU output; no API credentials belong here.
- `results/README.md` — result index.
- `tests/` — focused geometry and project checks.

Use `pyproject.toml` for the canonical dependencies and CLI entry points. `requirements-wsl.txt`, `requirements-noise.txt`, and `requirements-backend-noise.txt` are environment-specific dependency sets. Do not commit logs, cache files, credentials, or unfinished run directories.
