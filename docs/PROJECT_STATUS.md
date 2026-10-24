# Project status snapshot — 2026-10-25

This file is an archived-results snapshot, not live process monitoring. Only artifacts present in this repository are treated as completed results. Jobs running in another WSL session, Colab, or IBM Quantum account are not considered complete until their outputs are saved and checked here.

## Scientific setup

- Asymmetric H₂O stretch, H–O–H = 104.5°, one O–H fixed at 0.96 Å and the other at 2.20 Å unless a scan point is specified.
- STO-3G with frozen-core CAS(8e,6o); 12 active spin orbitals before particle-aware parity reduction and 10 mapped qubits afterward.
- At 2.20 Å: RHF = −74.623892380736 Ha; active-space CASCI = −74.860977098519 Ha; full STO-3G FCI = −74.861014224915 Ha. An independent mapped exact solve agrees with CASCI.
- All VQE accuracy and chemical-accuracy statements use active-space CASCI as the target. Threshold: 1.6 mHa.

## Completed archived findings

- Matched ansatz pilot (two starts/configuration; 150 objective-call budget): UCCSD×1 median error 7.193 mHa, best 0.064 mHa, 92 parameters, 1,955 level-3 CX; PUCCSD×1 median 8.524 mHa, 30 parameters, 458 CX; PUCCSD×2 median 2.876 mHa, 60 parameters, 916 CX; PUCCSD×3 median 0.187 mHa, best 0.115 mHa, 90 parameters, 1,374 CX. The pilot is small and budget-capped.
- Separate PUCCSD×3 SLSQP run saved at `results/ansatz/puccsd-reps3-slsqp100/`: energy −74.860885521062 Ha, 0.0916 mHa above CASCI, 90 parameters. `results/ansatz/puccsd3_params.json` stores that saved point.
- Warm-start PUCCSD×3 scan: errors 0.398, 0.290, 0.554 mHa at R₂ = 1.8, 2.2, 2.6 Å (three points only).
- Held-out optimizer study is for PUCCSD×1. Median absolute errors: L-BFGS-B 8.518, SLSQP 8.534, COBYLA 9.574, Powell 273.682, selected SPSA 106.586 mHa. Do not generalize the ordering to other ansätze or geometries.
- Fermionic ADAPT-VQE archive contains 11 of 16 requested macrocycles; final recorded error 3.473 mHa. This run is incomplete and misses the 1.6 mHa threshold.
- One low-shot synthetic noise example has 4,416 nominal shots and a +789.3 mHa error with 570.4 mHa propagated standard error. It demonstrates poor precision and is not an IBM-calibrated or QPU result.

## Hardware evidence

No completed IBM QPU output is archived in `results/hardware/`. Add a result only after saving the job ID, backend and calibration snapshot, circuit/layout metadata, measurement and mitigation settings, estimate, uncertainty, and comparison reference. Never commit credentials.

## Reproducibility

- `results/README.md` indexes the experiments and figures.
- `results/publication_figures/` has 11 SVG/PNG figures linked to source outputs. Captions identify sample sizes and incomplete/noisy runs.
- The submission notebook is `notebooks/h2o_asymmetric_stretch.ipynb`.
