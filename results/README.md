# Results index

This directory contains the archived evidence used by the README and figures. Energies are Hartree unless noted. VQE errors are relative to active-space CASCI unless a caption says otherwise.

## Folders

- `references/` — RHF, all-electron STO-3G FCI, frozen-core CASCI, mapped exact checks, and orbital-stability audit.
- `ansatz/` — UCCSD, PUCCSD, and fermionic ADAPT comparisons, convergence logs/data, and `puccsd3_params.json` (the saved 90-parameter PUCCSD×3 point).
- `geometry-scans/` — three-point warm-start PUCCSD×3 asymmetric O–H stretch scan.
- `optimizers/` — staged PUCCSD×1 optimizer tuning and held-out comparison, plus exploratory runs.
- `simulations/finite-shot-demo/` — one intentionally low-shot synthetic finite-shot estimate, with reported uncertainty. This is not hardware noise.
- `publication_figures/report/` — 15 report figures in PNG and PDF, plus their contact sheet. `publication_figures/analysis/` contains measurement, ADAPT, optimizer, and pilot analysis figures.
- `hardware/` — IBM job records for Hartree–Fock reference-state measurements. No optimized VQE state was run on hardware.

## Headline archived values

At R₂=2.20 Å, RHF is −74.623892380736 Ha, CASCI(8e,6o) is −74.860977098519 Ha, and all-electron STO-3G FCI is −74.861014224915 Ha. The active-space mapped exact check agrees with CASCI.

The two-start ansatz pilot used a 150 objective-call cap. PUCCSD×3 had median error 0.187 mHa, best 0.115 mHa, 90 parameters, and 1,374 level-3 CX. A separate saved PUCCSD×3 SLSQP run reached 0.0916 mHa error. Counts are logical transpilation metrics, not device-routed hardware counts.

ADAPT-VQE is incomplete at 11/16 requested cycles (3.473 mHa last recorded error). The low-shot simulation has 570.4 mHa propagated standard error. Neither supports a chemical-accuracy claim.

## Incomplete output directories

A directory without a completed summary is not a result. Historical long-running optimizer folders that lack final summaries are intentionally excluded from the public submission via `.gitignore`; consult local WSL logs if you need to recover them. Do not infer that a quiet process or log has completed.
