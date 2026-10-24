# Systematic asymmetric-H₂O optimizer study

## Reference

- Frozen-core CASCI: `-74.860977098519` Ha.
- Empirical PUCCSD(1) reference: `-74.852448678638` Ha.
- This is a multi-start SLSQP reference, not a proof of the global ansatz minimum.

- Best energy observed across all phases: `-74.852459608771` Ha (8.517 mHa above CASCI; lbfgsb, trial 2).
- Negative gaps to the SLSQP anchor mean another method improved that empirical anchor slightly; they do not indicate an energy below CASCI.

## SPSA setting selection

- Chosen on development runs only: `auto_calibration`.
- Parameters: `a=None`, `alpha=0.602`, `c=None`, `gamma=0.101`.
- `auto_calibration` selects Qiskit's calibration procedure, which recalibrates from each run's initial point; it is not one numeric schedule frozen from tuning. The run records the procedure and seed, but not the calibrated generator values.
- Full ranking: `spsa_tuning_ranked.csv`.

## Held-out optimizer results

| Optimizer | Runs | Median error vs CASCI (mHa) | IQR (mHa) | Median gap vs SLSQP anchor (mHa) | Paired median difference vs SLSQP (mHa) | Lower-error wins | Chemical-accuracy successes | Budget exhausted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| slsqp | 10 | 8.534 | 0.023 | 0.006 | — | — | 0/10 | 0/10 |
| lbfgsb | 10 | 8.518 | 0.001 | -0.010 | -0.016 | 10/10 | 0/10 | 0/10 |
| cobyla | 10 | 9.574 | 12.254 | 1.046 | 1.037 | 0/10 | 0/10 | 10/10 |
| powell | 10 | 273.682 | 98.724 | 265.153 | 265.151 | 0/10 | 0/10 | 10/10 |
| selected_spsa | 10 | 106.586 | 119.309 | 98.058 | 98.056 | 0/10 | 0/10 | 10/10 |

## Files

- `all_run_metrics.csv`: one row per optimizer run.
- `all_convergence_history.csv`: raw recorded energy traces.
- `heldout_checkpoints.csv`: held-out energies at common evaluation checkpoints.
- `heldout_convergence.png`: held-out convergence plot.
- `study_report.json`: machine-readable complete summary.
- Each subrun directory retains its original `summary.json`, history, plot, and driver log.

## Interpretation limits

- All objectives are ideal exact-statevector energies; no finite-shot or hardware-noise claim.
- The SLSQP multi-start minimum is an empirical ansatz reference, not a mathematical global-optimum certificate.
- SLSQP reverse-mode gradients are counted separately from objective calls; equal objective-call budgets do not imply equal classical wall-clock work.
- The tuning and held-out seed ranges are disjoint; held-out results do not select SPSA settings.
