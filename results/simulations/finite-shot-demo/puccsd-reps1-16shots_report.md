# H₂O noisy simulator result

This is a fixed optimized PUCCSD/UCCSD state evaluated with finite shots in local Aer under the explicitly stated synthetic noise model. It is not IBM hardware data.

- Ansatz: puccsd, reps=1, 30 parameters.
- Qubits: 10; QWC measurement groups: 276.
- Shots/group: 16; seeds: 11.
- Ideal saved energy: -74.852459541 Ha (|ΔCASCI|=8.518 mHa).
- Noisy mean: -74.071666227 ± 0.570414 Ha (propagated sampling SE).
- Noise bias vs ideal: +780.793 mHa.
- Noisy |ΔCASCI|: 789.311 mHa.
- Synthetic model: p1=0.0001, p2=0.001, readout=0.01.

Interpretation: the run demonstrates finite-shot noisy simulation of the saved H₂O ansatz. It does not demonstrate noisy re-optimization, error mitigation, or real-device performance. The sampling uncertainty excludes uncertainty in the synthetic noise rates.
