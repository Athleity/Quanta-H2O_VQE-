# H₂O VQE publication figure catalog

Primary files are editable SVG vector figures; paired PNG previews are 4200 × 2700 px at 600 dpi. They were generated from archived CSV/JSON; no values were synthesized. Lines through bond-scan points are visual guides only.

## FIGURE 1 — Asymmetric O–H stretch: reference and VQE energies

R₂ = 1.8, 2.2, and 2.6 Å. Energies are total electronic plus nuclear-repulsion values from the saved scan.

Source: results/scans/puccsd-reps3-scan/asymmetric_stretch_scan.csv

## FIGURE 2 — Correlation recovery along the asymmetric stretch

Three geometry points only. No values between the sampled geometries are inferred.

Source: results/scans/puccsd-reps3-scan/asymmetric_stretch_scan.csv

## FIGURE 3 — Accuracy–entangling-resource trade-off

CX counts are level-3 transpiler estimates. Min–max spans two starts (n=2), not a confidence interval.

Source: results/ansatz/ansatz-resource-pilot/ansatz_runs.csv

## FIGURE 4 — Circuit-resource growth with paired-ansatz repetitions

Counts are from the recorded level-3 compilation of the logical circuit, not hardware-routed execution.

Source: results/ansatz/ansatz-resource-pilot/ansatz_runs.csv

## FIGURE 5 — Observed restart-to-restart variability

Two starts per configuration only (n=2); observed range is not a confidence interval or a global-minimum guarantee.

Source: results/ansatz/ansatz-resource-pilot/ansatz_runs.csv

## FIGURE 6 — Optimization traces under a fixed evaluation cap

The pilot used a 150-objective-evaluation cap. Gradient evaluations and wall-clock cost are not represented by this x-axis.

Source: results/ansatz/ansatz-resource-pilot/*/optimization_history.csv

## FIGURE 7 — Held-out optimizer outcomes for PUCCSD(1)

Ten starts per optimizer. Results use ideal statevector objectives; evaluation count is not equal to wall-clock or hardware cost.

Source: results/optimizers/systematic-optimizer-study/all_run_metrics.csv

## FIGURE 8 — Optimizer convergence at common evaluation checkpoints

Objective evaluations are a budget proxy. Exact gradients, their cost, and elapsed time differ across optimizers.

Source: results/optimizers/systematic-optimizer-study/heldout_checkpoints.csv

## FIGURE 9 — SPSA calibration grid: development-stage results

Tuning data only, not held-out performance. The selected auto-calibration schedule is run-dependent.

Source: results/optimizers/systematic-optimizer-study/spsa_tuning_ranked.csv

## FIGURE 10 — Fermionic ADAPT-VQE: progress through the interrupted run

The run stopped after 11 of 16 requested cycles. Final recorded error: 3.473 mHa vs active-space CASCI; chemical accuracy was not reached.

Source: results/ansatz/adapt-slsqp-final-16cycle/adapt_progress.csv

## FIGURE 11 — Low-shot synthetic noise: uncertainty overwhelms the ideal error

PUCCSD(1), 10 mapped qubits; 4,416 shots total. Synthetic noise p₁=10⁻⁴, p₂=10⁻³, symmetric readout flip=1%. Noisy estimate error +789.3 mHa ±570.4 mHa (one propagated sampling SE, one seed); this is too imprecise to support a chemical-accuracy claim.

Source: results/noisy-demo/puccsd-reps1-16shots.json

## Design and interpretation

Figures follow scientific plotting principles: unit-labelled axes, uncluttered white canvas, accessible color with marker-shape redundancy, and editable vector output. Nature’s guide recommends accessible palettes, readable sans-serif labels, axes with units, and vector artwork: https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/.
The plot structures reflect published VQE work: molecular energy/error curves for water (https://pubs.rsc.org/en/content/articlehtml/2024/cp/d3cp05570a; https://pubs.rsc.org/en/content/articlepdf/2025/dd/d5dd00202h), optimizer convergence for fixed ansatz (https://doi.org/10.1038/s42005-025-02375-9), and error/resource analyses under noise (https://doi.org/10.1103/PhysRevA.109.042413).
Ansatz pilot has n=2 starts only. Optimizer counts are objective evaluations, not equivalent compute cost. ADAPT data is partial at 11/16 cycles (stopped at 3.473 mHa error). Noise plot is one synthetic finite-shot run with very large uncertainty; it is neither calibrated backend noise nor hardware data.
The backend-calibrated Aer study was still marked running with zero completed cases; it is not plotted as a result. No completed IBM QPU data were available when this figure set was generated.