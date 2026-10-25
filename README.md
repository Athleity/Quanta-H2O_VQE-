# Quanta

## A variational quantum eigensolver study of stretched water

**Hackathon track:** VQE for Chemistry & Materials  
**Molecule:** Water, H₂O  
**Main geometry:** One O–H bond is 0.96 Å, the other is 2.20 Å, and the H–O–H angle is 104.5°  
**Project question:** How does the accuracy of chemistry-inspired VQE circuits change as their size increases?  
**GitHub repository:** [Athleity/Quanta-H2O_VQE-](https://github.com/Athleity/Quanta-H2O_VQE-)

> **Important distinction:** The best VQE energy in this project came from a noiseless classical simulation. The IBM hardware jobs measured the Hartree–Fock reference state only. They did not run the optimized PUCCSD circuit, and they did not optimize VQE parameters on hardware.

## Project summary

This project studies the ground-state energy of water when one O–H bond is stretched while the other bond remains fixed. Stretching a bond makes the electronic structure harder to describe with a simple Hartree–Fock calculation. It provides a useful test of whether a VQE circuit can represent the molecular state accurately.

We created the molecular Hamiltonian from the water geometry using PySCF. We reduced the problem to a six-orbital active space, mapped it to qubits, and checked its energy against classical calculations. We then compared three chemistry-inspired VQE approaches in noiseless simulation:

* UCCSD
* Paired UCCSD, abbreviated PUCCSD
* Fermionic ADAPT-VQE

We also submitted fixed Hartree–Fock circuits to IBM Quantum hardware. Those hardware runs tested the measurement and execution workflow. They were not hardware VQE runs.

### Main findings

* In the small ansatz comparison, PUCCSD became more accurate as the number of repetitions increased.
* The best PUCCSD with three repetitions result in the supplied run logs was 0.00152 mHa above the active-space CASCI reference. That run used its full 1,500-evaluation budget, so we report it as the best observed, budget-limited result.
* In a separate three-geometry scan, PUCCSD with three repetitions stayed within 0.554 mHa of the CASCI reference at each of the three tested geometries.
* The shared ADAPT-VQE log contains 11 completed macrocycles. Its last recorded energy was 3.473 mHa above CASCI, outside the 1.6 mHa threshold.
* All four IBM hardware jobs measured the Hartree–Fock reference state. None measured the PUCCSD circuit or a VQE-optimized state.

## What problem are we solving?

Our main question is:

> **For stretched water in a fixed active-space model, how does VQE energy accuracy change as we increase the size of a chemistry-inspired circuit?**

A useful VQE circuit must represent the molecular state accurately. At the same time, a larger circuit usually needs more parameters and more gates. Those gates can make the circuit harder to run, especially on noisy hardware.

For that reason, we report both energy accuracy and circuit-resource estimates. We do not treat a lower energy as the only measure of a better method.

## Why study stretched water?

Hartree–Fock is a useful starting point for many molecules. It represents the electrons using a single main electronic configuration. When a chemical bond is stretched, other configurations can become more important. A method that works well near equilibrium may become less accurate in this situation.

We fix one O–H bond and increase the length of the second O–H bond. This produces an asymmetric geometry and lets us examine how the methods perform at a controlled set of bond lengths.

This is a small-basis computational study. It does not claim to provide the exact energy of real water in a complete basis set.

## Geometry and electronic model

The oxygen atom is placed at the origin. The first hydrogen is placed 0.96 Å away from oxygen. The second hydrogen is placed at distance R₂ from oxygen, with the H–O–H angle fixed at 104.5°.

The coordinates used in the calculation are:

```text
O  0.0                         0.0  0.0
H  0.0                         0.0  0.96
H  R2 * sin(104.5 degrees)     0.0  R2 * cos(104.5 degrees)
```

The main comparison uses R₂ = 2.20 Å. The bond scan uses R₂ = 1.80 Å, 2.20 Å, and 2.60 Å.

The electronic-structure calculations use the STO-3G basis. For the quantum calculations, we use a frozen-core CAS(8e,6o) model. This means that eight electrons are treated as active in six spatial orbitals, while the oxygen 1s orbital is frozen.

Six spatial orbitals correspond to twelve spin orbitals. We map the active-space Hamiltonian with the parity mapping and apply two-qubit reduction. The resulting quantum problem has ten qubits.

PySCF generates the Hamiltonian from the geometry and molecular integrals. The Pauli Hamiltonian is not typed into the program by hand.

## How VQE works in this project

The Hamiltonian is the mathematical description of the electronic energy for the model we selected. A quantum circuit prepares a trial electronic state. The program estimates the average energy of that state.

The circuit contains adjustable parameters. A classical optimizer changes those parameters to lower the estimated energy. We repeat that process until the optimizer reaches its stopping condition or its evaluation budget.

The workflow is:

1. Set the water geometry, basis, and active space.
2. Use PySCF to calculate classical reference energies.
3. Build the active-space Hamiltonian and map it to ten qubits.
4. Check the mapped active-space ground energy against the CASCI calculation.
5. Prepare the Hartree–Fock reference state.
6. Build a UCCSD, PUCCSD, or ADAPT-VQE circuit.
7. Optimize circuit parameters using a classical optimizer and noiseless statevector calculations.
8. Compare the VQE energy with the frozen-core CASCI energy.
9. Record the parameter count and transpiled CX gate estimate where available.
10. Separately, run fixed Hartree–Fock circuits on IBM hardware.

The hardware workflow did not perform step 7. No VQE parameter optimization was performed on the IBM device.

## Reference energies at the main geometry

At R₂ = 2.20 Å, the reference calculations gave:

| Calculation | Energy in Hartree | How we use it |
|---|---:|---|
| RHF | −74.623892380736 | Energy of the Hartree–Fock reference state |
| Frozen-core CASCI(8e,6o) | −74.860977098519 | Reference used to calculate active-space VQE errors |
| Exact solve of the mapped active-space Hamiltonian | −74.860977098519 | Independent check of the active-space result |
| Full STO-3G FCI | −74.861014224915 | All-electron STO-3G reference in a different configuration space |

The VQE errors in this project are measured relative to frozen-core CASCI. Full STO-3G FCI and frozen-core CASCI are different calculations. They do not describe the same configuration space, so we do not substitute one for the other when calculating VQE errors.

The ideal Hartree–Fock energy is 237.085 mHa above the CASCI energy.

We use 1.6 mHa as the chemical-accuracy threshold relative to the active-space CASCI reference. This threshold applies to the model used here. It is not a claim of 1.6 mHa accuracy relative to the complete-basis-set energy of water.

## VQE circuit approaches

### UCCSD

UCCSD uses single and double electron excitations to build a parameterized quantum state. It is chemistry motivated, but its circuit can be large.

### PUCCSD

PUCCSD uses paired excitations. In the tested setup, one repetition had fewer parameters and fewer estimated CX gates than the single-repetition UCCSD circuit. Additional repetitions made the PUCCSD circuit larger and improved the observed energy accuracy.

The name PUCCSD here refers to the Qiskit Nature ansatz used by this project. It should not be assumed to be identical to every implementation described as k-UpCCGSD.

### Fermionic ADAPT-VQE

ADAPT-VQE grows a circuit during the calculation. It evaluates gradients for a pool of candidate excitation operators, selects an operator, adds it to the circuit, and reoptimizes the circuit parameters.

The ADAPT result below is limited to the completed macrocycles present in the supplied log.

## Noiseless ansatz comparison

The resource pilot used two starts for each setting and a maximum of 150 objective evaluations. CX counts are estimates from level-3 logical circuit transpilation. They are not hardware-routed gate counts.

| Ansatz | Repetitions | Parameters | Estimated CX gates | Median CASCI error in mHa | Best observed error in mHa | Starts within 1.6 mHa |
|---|---:|---:|---:|---:|---:|---:|
| UCCSD | 1 | 92 | 1,955 | 7.193 | 0.064 | 1 of 2 |
| PUCCSD | 1 | 30 | 458 | 8.524 | 8.518 | 0 of 2 |
| PUCCSD | 2 | 60 | 916 | 2.876 | 2.517 | 0 of 2 |
| PUCCSD | 3 | 90 | 1,374 | 0.187 | 0.115 | 2 of 2 |

In this pilot, increasing the PUCCSD repetition count improved the observed energy accuracy. It also increased the parameter count and the estimated CX count.

The pilot contains only two starts per setting. It is useful for comparing these tested runs, but it is not enough to prove a global optimum or guarantee that a new run will achieve the same energy.

### Best logged PUCCSD result

The best PUCCSD with three repetitions energy in the run output shared for this project was:

| Quantity | Value |
|---|---:|
| VQE energy | −74.860975578262 Ha |
| Frozen-core CASCI energy | −74.860977098519 Ha |
| Difference from CASCI | 0.00152 mHa |
| Circuit parameters | 90 |
| Objective evaluation budget | 1,500 |
| Threshold comparison | Within 1.6 mHa |

This result is from a noiseless classical statevector simulation. It used the full evaluation budget. We therefore describe it as the **best observed, budget-limited result**. It does not establish that the optimizer fully converged or that the result is a global minimum.

A separate resource-pilot run reported a PUCCSD with three repetitions error of 0.115 mHa. That is a different run and is reported separately in the ansatz comparison table.

## Asymmetric O–H bond scan

The warm-start PUCCSD with three repetitions scan used the optimized parameters from one geometry to initialize the next geometry.

| R₂ in Å | CASCI energy in Ha | PUCCSD energy in Ha | Absolute difference in mHa |
|---:|---:|---:|---:|
| 1.80 | −74.887678538893 | −74.887280139717 | 0.398 |
| 2.20 | −74.860977098519 | −74.860687456423 | 0.290 |
| 2.60 | −74.853880734062 | −74.853326368035 | 0.554 |

All three reported PUCCSD energies are within 1.6 mHa of their corresponding CASCI references.

This is a three-point scan, not a dense potential-energy curve. A full STO-3G FCI value at R₂ = 2.60 Å was inconsistent between separate outputs, so we have not included a full-FCI comparison at that geometry.

## Classical optimizer comparison

The held-out optimizer comparison tested PUCCSD with one repetition. The archived summary reports these median absolute errors relative to CASCI:

| Optimizer | Median absolute error in mHa |
|---|---:|
| L-BFGS-B | 8.518 |
| SLSQP | 8.534 |
| COBYLA | 9.574 |
| SPSA with the selected schedule | 106.586 |
| Powell | 273.682 |

These values describe the tested circuit, initialization procedure, seeds, hyperparameters, and evaluation budget. They are not a universal ranking of optimizers.

Objective-evaluation counts also need careful interpretation. They do not directly measure wall-clock time, total gradient cost, number of quantum shots, or hardware workload. In particular, a gradient evaluation in a noiseless simulator is not automatically equivalent to a gradient evaluation on a quantum device.

## Fermionic ADAPT-VQE progress

The final ADAPT-VQE run requested 16 macrocycles. The shared log contains completed results for the first 11 cycles. The energy improved across those completed cycles.

| Completed cycle | Energy in Ha | Absolute error from CASCI in mHa |
|---:|---:|---:|
| 1 | −74.833020889 | 27.956 |
| 2 | −74.847177291 | 13.800 |
| 3 | −74.849676468 | 11.301 |
| 4 | −74.852336686 | 8.640 |
| 5 | −74.854687517 | 6.290 |
| 6 | −74.855144209 | 5.833 |
| 7 | −74.855814459 | 5.163 |
| 8 | −74.856541590 | 4.436 |
| 9 | −74.856845948 | 4.131 |
| 10 | −74.857182481 | 3.795 |
| 11 | −74.857504538 | 3.473 |

After 11 completed cycles, the energy was 3.473 mHa above CASCI. That is outside the 1.6 mHa threshold. The shared log does not contain completed results for cycles 12 through 16, so no result is claimed for those cycles.

## Finite-shot local simulation

A separate local Aer run evaluated a fixed PUCCSD with one repetition state using finite shots. The supplied record reports 16 shots for each of 276 qubit-wise-commuting groups, giving 4,416 nominal shots in total, with one simulator seed.

| Quantity | Reported value |
|---|---:|
| Estimated energy | −74.071666227 Ha |
| Difference from CASCI | +789.311 mHa |
| Reported standard error | 570.414 mHa |
| Nominal shot count | 4,416 |
| Simulator seeds | 1 |

The uncertainty is large, so this result does not support a precise energy claim or a meaningful accuracy comparison. It is a local finite-shot simulation, not an IBM hardware result.

The noise configuration should be reported from the saved run settings. Do not infer particular noise rates from the energy alone.

## IBM Quantum hardware measurements

### What the IBM jobs measured

All four IBM jobs measured the **Hartree–Fock reference state**. The reference circuit uses four X gates and has zero entangling gates.

The jobs did not measure the optimized PUCCSD state. The PUCCSD with three repetitions circuit, with an estimated 1,374 logical CX gates, was not run on hardware.

Jobs B, C, and D measured the 79 Z-only terms of the mapped Hamiltonian. For the ideal Hartree–Fock state, terms containing X or Y have zero expectation because the state is a computational-basis state. A simulation check found that the ideal Z-only energy and the full Hamiltonian energy agreed within 0.000000001 Ha.

### Hardware setup

| Item | Recorded information |
|---|---|
| IBM backend | `ibm_kingston`, 156 qubits |
| Calibration snapshot | 2026-10-24 20:25 UTC |
| Runtime primitive | Qiskit Runtime EstimatorV2 |
| Software versions | Qiskit 1.4.3, qiskit-ibm-runtime 0.40.1, qiskit-nature 0.7.2 |
| Molecule and basis | H₂O, STO-3G |
| Geometry | R₁ = 0.96 Å, R₂ = 2.20 Å, angle = 104.5° |
| Active space | CAS(8e,6o), oxygen 1s frozen |
| Qubit mapping | Parity mapping with two-qubit reduction |
| Mapped problem size | 10 qubits |
| State measured | Hartree–Fock reference |
| Reference circuit | Four X gates, zero entangling gates |

### Job results

The total energies include the molecular Hamiltonian constant. The offset is calculated relative to the ideal Hartree–Fock energy, −74.623892 Ha. The reported standard errors are statistical estimates and do not include every source of systematic device error.

| Job | IBM job ID | Observable and settings | Total energy in Ha | Standard error in mHa | Offset from ideal HF in mHa |
|---|---|---|---:|---:|---:|
| A | `dbehvvfgdj9s73flrceg` | Full 1,079-term Hamiltonian; 276 groups; resilience level 1; target precision 0.04 Ha | −73.967321 | 346.52 | +656.571 |
| B | `dbei45vpc3tc739lomf0` | 79 Z-only terms; one group; resilience level 1 with TREX and twirling; target precision 0.005 Ha | −74.542299 | 2,140.26 | +81.593 |
| C | `dbei5tvpc3tc739lop2g` | 79 Z-only terms; resilience level 0; 100,000 shots requested | −74.327453 | 3.45 | +296.439 |
| D | `dbei8tom94ac738rsp90` | 79 Z-only terms; resilience level 0; 100,000 shots requested; layout selected from low-readout-error qubits | −74.573420 | 1.47 | +50.472 |

Job A took 104 seconds of wall time. Job B used about 21 seconds of QPU time and used 40,000 service shots across 32 randomizations. Job B did not reach its requested 5 mHa precision. Runtime details for Jobs C and D were not supplied.

For Job D, the selected qubits were 148, 42, 117, 149, 154, 44, 91, 134, 40, and 89. Their mean estimated readout error was 0.00310. The device-wide mean from the calibration information used for that run was 0.02016.

### What we can conclude from the hardware jobs

The IBM jobs demonstrate execution of the fixed Hartree–Fock circuit and its observable on a real quantum device. They exercise Hamiltonian construction, mapping, transpilation, observable layout, and EstimatorV2 submission.

The jobs do **not** show a VQE-optimized result on hardware. They do **not** measure the PUCCSD circuit. They do **not** establish chemical accuracy on hardware.

Job B’s measured energy was closer to the ideal Hartree–Fock energy than Job C’s measured energy. However, Job B’s reported standard error was 2,140.26 mHa. These results do not establish a statistically reliable improvement from mitigation.

Job D had a smaller measured offset and standard error than Job C in these individual jobs. This one comparison does not establish a general improvement from choosing qubits with lower estimated readout error.

The cause of Job C’s large offset has not been independently verified. Readout error may contribute, but it has not been confirmed as the cause. All reported hardware standard errors are statistical only.

## Figures

Add the final figure images to the repository and update the filenames below to match the files you include. Use PNG files for the GitHub README preview. Keep the high-resolution PDF or SVG versions for the report if they are available.

```text
results/publication_figures/
```

Suggested figures for the README:

1. Ansatz accuracy versus estimated CX resources
2. PUCCSD error across the three bond lengths
3. ADAPT-VQE error across the 11 completed cycles
4. IBM Hartree–Fock measurements with statistical uncertainty bars

Do not hide the large uncertainty bars for Jobs A and B. Each caption should say whether the figure shows noiseless simulation, local finite-shot simulation, or hardware measurement.

<!-- Add the final figure image links here after copying the files into results/publication_figures/. -->

## Reproducing the calculations

The commands below assume Linux, WSL, or Colab.

### Install the project

```bash
git clone https://github.com/Athleity/Quanta-H2O_VQE-.git
cd Quanta-H2O_VQE-
python -m pip install --prefer-binary -e .
```

For the documented WSL dependencies, use:

```bash
python -m pip install --prefer-binary -r config/requirements/requirements-wsl.txt
```

For local Aer noise simulation, install the additional dependencies:

```bash
python -m pip install --prefer-binary -r config/requirements/requirements-noise.txt
```

PySCF is intended to run in Linux, WSL, or Colab. A native Windows Python installation may need a separate supported environment.

### Calculate the reference energies

```bash
h2o-vqe \
  --reference-only \
  --stretched-oh 2.20 \
  --output results/references/reproduce-r2.20
```

### Run a PUCCSD calculation

```bash
h2o-vqe \
  --methods puccsd \
  --ansatz-reps 3 \
  --optimizer slsqp \
  --restarts 1 \
  --seed 20261023 \
  --maxiter 100 \
  --output results/ansatz/reproduce-puccsd3-r2.20
```

An optimizer may stop at a different point when the calculation is repeated. Reproducing a particular result can depend on package versions, initialization, random seeds, optimizer settings, and evaluation budgets.

### Run the three-point bond scan

```bash
h2o-vqe \
  --methods puccsd \
  --ansatz-reps 3 \
  --optimizer slsqp \
  --restarts 1 \
  --scan-r2 1.8,2.2,2.6 \
  --warm-start-scan \
  --output results/geometry-scans/reproduce-puccsd3-scan
```

### Open the notebook

Open `notebooks/h2o_asymmetric_stretch.ipynb` in Jupyter or Colab. Run the setup cell before running the calculation cells.

Never commit IBM API keys, tokens, or private account information to a public repository. Use the notebook platform’s secret manager or enter credentials at runtime.

## Repository layout

| Path | Purpose |
|---|---|
| `README.md` | Project question, methods, results, and reproduction instructions |
| `pyproject.toml` | Python package settings and command-line entry point |
| `src/h2o_vqe/` | Main chemistry, VQE, and noise code |
| `scripts/` | Experiment runners and figure-generation tools |
| `notebooks/` | Interactive project notebook |
| `docs/` | Research notes and project documentation |
| `config/requirements/` | Dependency lists for different environments |
| `results/` | Saved calculations, data, and figures |
| `tests/` | Project checks |

## Team

**Team name:** Quanta  
**Hackathon track:** VQE for Chemistry & Materials

| Member | Institution | Department or field | Career level |
|---|---|---|---|
| Priyansh Bhavsar | IIT Jodhpur | Physics | Bachelor’s student |
| Mohammed Hasan Iqbal | IIT Bombay | Physics | Student |
| Yahya Mohammed | Nile University | Computer Science | Student |
| Donia Mohammed | Zagazig University | Chemistry and Computer Science | Student |

## Limitations

* The calculations use the STO-3G basis and frozen-core CAS(8e,6o) model. They are not complete-basis-set exact energies for water.
* Full STO-3G FCI and frozen-core CASCI are different reference calculations. The reported VQE errors use CASCI.
* The bond scan has only three geometries. It is not a densely sampled potential-energy curve.
* The resource pilot has two starts per setting and a finite objective-evaluation cap.
* The best logged PUCCSD with three repetitions value used the full 1,500-evaluation budget. It is a best observed result, not proof of convergence or a global minimum.
* The optimizer comparison describes only the tested PUCCSD with one repetition setup and its recorded settings.
* CX counts are level-3 logical transpilation estimates. They are not routed hardware gate counts.
* The shared ADAPT-VQE log contains 11 completed macrocycles from a request for 16.
* The local finite-shot example used one simulator seed and has a large reported uncertainty.
* IBM hardware jobs measured the Hartree–Fock reference state only.
* The IBM jobs did not optimize VQE parameters on hardware.
* Hardware standard errors are statistical estimates and do not capture all systematic device effects.
* A noisy energy estimate below a reference energy is not, by itself, evidence of a better variational state. The uncertainty and systematic error must also be considered.

## References

1. Bian et al., “Quantum computing methods for electronic states of the water molecule,” *Molecular Physics* (2019). [arXiv:1804.05453](https://arxiv.org/abs/1804.05453)
2. Lee et al., “Generalized Unitary Coupled Cluster Wavefunctions for Quantum Computation,” *Journal of Chemical Theory and Computation*, volume 15, pages 311–324 (2019). [DOI: 10.1021/acs.jctc.8b01004](https://doi.org/10.1021/acs.jctc.8b01004)
3. Grimsley et al., “An adaptive variational algorithm for exact molecular simulations on a quantum computer,” *Nature Communications*, volume 10, article 3007 (2019). [DOI: 10.1038/s41467-019-10988-2](https://doi.org/10.1038/s41467-019-10988-2)
4. Qiskit Nature documentation: [PUCCSD API](https://qiskit-community.github.io/qiskit-nature/stubs/qiskit_nature.second_q.circuit.library.PUCCSD.html), [VQE with UCC](https://qiskit-community.github.io/qiskit-nature/howtos/vqe_ucc.html), and [ADAPT-VQE guide](https://qiskit-community.github.io/qiskit-nature/howtos/adapt_vqe.html).
5. The expanded literature review is in [`docs/RESEARCH.md`](docs/RESEARCH.md).
