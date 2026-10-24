# H₂O ansatz and resource comparison

Geometry: fixed O–H = 0.9600 Å; stretched O–H = 2.2000 Å; angle = 104.500°.
Model: STO-3G, frozen-core CAS(8e,6o); exact statevector energies.
Optimizer: lbfgsb; call cap = 150; starts per configuration = 2.

Median errors are compared with each geometry's active-space CASCI. IQR describes the spread of runs; it is not a confidence interval.
The CX-evaluation product is a circuit-work proxy only, not a measured hardware runtime or shot count.

| Ansatz | Runs | Median error (mHa) | IQR (mHa) | Best (mHa) | Within 1.6 mHa | Parameters | CX, level 3 | Depth, level 3 | Budget-capped |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| UCCSD ×1 | 2 | 7.193 | 7.129 | 0.064 | 1/2 | 92 | 1955 | 2312 | 1/2 |
| PUCCSD ×1 | 2 | 8.524 | 0.006 | 8.518 | 0/2 | 30 | 458 | 464 | 0/2 |
| PUCCSD ×2 | 2 | 2.876 | 0.359 | 2.517 | 0/2 | 60 | 916 | 910 | 2/2 |
| PUCCSD ×3 | 2 | 0.187 | 0.072 | 0.115 | 2/2 | 90 | 1374 | 1356 | 2/2 |

## Interpretation limits

- Multi-start minima are empirical; they do not prove a global minimum.
- A common objective-call cap does not equalize wall time or gradient cost.
- Circuit counts are transpiler estimates, not device-routed metrics.
- The chemical-accuracy threshold is relative to active-space CASCI; it does not remove STO-3G or active-space model error.
- This is noiseless simulation. It does not establish finite-shot or hardware performance.
- Repetition count changes both ansatz expressibility and circuit cost; that trade-off is the experiment.

Plot: `ansatz_accuracy_resource_pareto.png`.
