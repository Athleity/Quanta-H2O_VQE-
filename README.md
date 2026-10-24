# Quanta
## Variational quantum eigensolver study of asymmetrically stretched water

**Track:** VQE for Chemistry & Materials  
**Molecule:** Water, H₂O  
**Main geometry:** \(R_1=0.96\) Å, \(R_2=2.20\) Å, and \(\angle\mathrm{HOH}=104.5^\circ\)  
**Main comparison:** Accuracy and circuit resources for chemistry-inspired VQE ansätze  
**Repository:** [Athleity/Quanta-H2O_VQE-](https://github.com/Athleity/Quanta-H2O_VQE-)

> **Please read this distinction first.** The most accurate VQE energy reported here comes from a noiseless classical statevector simulation. The IBM Quantum jobs measured the Hartree–Fock reference state only. They did not run the PUCCSD circuit, optimize VQE parameters on hardware, or demonstrate chemical accuracy on hardware.

## The project in one minute

We study whether a variational quantum eigensolver can describe water when one O–H bond is stretched while the other stays fixed. Stretching a bond makes electron correlation more important, so it tests whether a chosen quantum circuit can represent the molecular ground state.

We build the molecular Hamiltonian from the water geometry using PySCF, then reduce the electronic problem to a frozen-core active space. We compare UCCSD, paired UCCSD, and fermionic ADAPT-VQE in noiseless simulation. We check the active-space calculation against classical reference calculations and an independent exact solve of the mapped Hamiltonian. We also measure the Hartree–Fock reference state on IBM hardware.

The main findings are:

* In the small ansatz resource pilot, PUCCSD needed more repetitions to reach the active-space chemical-accuracy threshold.
* The three-repetition PUCCSD circuit came within 0.00152 mHa of the CASCI reference in the best logged optimization run, using the full evaluation budget.
* A separate three-geometry scan stayed within 0.554 mHa of CASCI at all three tested geometries.
* The recorded ADAPT-VQE run improved its energy through 11 completed macrocycles, but its last recorded error, 3.473 mHa, remained above the 1.6 mHa threshold.
* The IBM jobs measured the Hartree–Fock reference state. They tested parts of the hardware execution workflow, not the VQE ansatz.

## What question are we asking?

Our main question is:

> **For asymmetrically stretched H₂O in a fixed active-space model, how does the energy accuracy of chemistry-inspired VQE ansätze change as their circuit resources increase?**

This question is useful because a VQE circuit has to balance two competing needs. It must be expressive enough to represent the molecular ground state, but its gate count and depth should remain manageable. A lower energy error alone is not a complete comparison if it requires a much larger circuit.

We therefore report energy error alongside the number of circuit parameters and the transpiled CX gate count where available. We treat those CX counts as logical circuit estimates, not as counts measured on IBM hardware.

## Why stretch one O–H bond?

At equilibrium, a single-reference method such as Hartree–Fock can provide a useful starting state. As a bond is stretched, additional electronic configurations can become important. A circuit that performs well only near equilibrium may not describe this more strongly correlated situation accurately.

We keep one O–H distance fixed and vary the other. This makes the geometry asymmetric and lets us compare the methods across a controlled set of structures.

This is a finite model study in the STO-3G basis. It is not a claim that this small basis gives a complete-basis-set description of real water.

## Molecular geometry and electronic model

The coordinates are defined by

\[
\begin{aligned}
\mathrm{O}  &= (0,\;0,\;0),\\
\mathrm{H}_1 &= (0,\;0,\;R_1),\\
\mathrm{H}_2 &= (R_2\sin\theta,\;0,\;R_2\cos\theta),
\end{aligned}
\]

where

\[
R_1=0.96\ \text{\AA},\qquad
\theta=104.5^\circ.
\]

The primary comparison uses \(R_2=2.20\) Å. The geometry scan uses \(R_2=1.80\), \(2.20\), and \(2.60\) Å.

The electronic structure is calculated in the STO-3G basis. The quantum calculation uses a frozen-core CAS(8e,6o) active space: eight active electrons in six spatial orbitals, with the oxygen 1s orbital frozen. These six spatial orbitals correspond to twelve spin orbitals. The parity mapping with two-qubit reduction gives a ten-qubit problem.

The molecular Hamiltonian is generated from the geometry and active-space integrals. It is not a manually entered Pauli Hamiltonian.

## How VQE works in this project

The electronic Hamiltonian \(H\) describes the energy of the electrons in the chosen molecular model. VQE prepares a parameterized quantum state \(\lvert\psi(\boldsymbol{\theta})\rangle\) and estimates its energy,

\[
E(\boldsymbol{\theta})
=
\langle\psi(\boldsymbol{\theta})\rvert
H
\lvert\psi(\boldsymbol{\theta})\rangle.
\]

A classical optimizer changes the parameters \(\boldsymbol{\theta}\) to lower this energy. Since the exact ground-state energy is the minimum possible expectation value of \(H\), the ideal noiseless VQE energy should approach the ground-state energy from above.

Our workflow is:

1. Define the H₂O geometry and basis.
2. Use PySCF to calculate the mean-field and correlated classical references.
3. Construct the frozen-core CAS(8e,6o) Hamiltonian.
4. Map that Hamiltonian to ten qubits and verify its ground energy by an independent exact solve.
5. Prepare the Hartree–Fock reference state and build the selected VQE ansatz.
6. Optimize the ansatz parameters using a classical optimizer and noiseless statevector energy evaluations.
7. Compare the VQE energy with the frozen-core CASCI energy and record circuit-resource estimates.
8. For the hardware study, submit fixed Hartree–Fock reference-state circuits to IBM Runtime. No hardware VQE optimization was performed.

## Reference energies at the main geometry

At \(R_2=2.20\) Å, the reported reference energies are:

| Reference calculation | Energy (Ha) | What it represents |
|---|---:|---|
| RHF | −74.623892380736 | Hartree–Fock reference-state energy |
| Frozen-core CASCI(8e,6o) | −74.860977098519 | Target used for active-space VQE errors |
| Mapped active-space exact solve | −74.860977098519 | Independent check of the CASCI active-space energy |
| Full STO-3G FCI | −74.861014224915 | All-electron STO-3G calculation in a different configuration space |

The VQE errors in this README are measured relative to frozen-core CASCI. Full STO-3G FCI and frozen-core CASCI are different calculations and must not be substituted for one another.

The ideal Hartree–Fock reference state is about **237.085 mHa above the CASCI energy**. This is the starting point for the variational optimization.

The chemical-accuracy threshold used in this project is **1.6 mHa relative to the active-space CASCI reference**. It is a comparison threshold for this model, not a claim of accuracy relative to the complete-basis-set molecular energy.

## Noiseless ansatz comparison

We compared the following circuits:

* **UCCSD:** a unitary coupled-cluster singles-and-doubles ansatz.
* **PUCCSD:** a paired UCCSD ansatz that restricts the excitation structure.
* **Fermionic ADAPT-VQE:** an adaptive circuit that adds one selected excitation operator at a time.

The first resource comparison used two starts per setting and a cap of 150 objective evaluations. The CX counts are level-3 transpilation estimates.

| Ansatz | Repetitions | Parameters | Estimated CX gates | Median CASCI error (mHa) | Best observed error (mHa) | Starts within 1.6 mHa |
|---|---:|---:|---:|---:|---:|---:|
| UCCSD | 1 | 92 | 1,955 | 7.193 | 0.064 | 1 of 2 |
| PUCCSD | 1 | 30 | 458 | 8.524 | 8.518 | 0 of 2 |
| PUCCSD | 2 | 60 | 916 | 2.876 | 2.517 | 0 of 2 |
| PUCCSD | 3 | 90 | 1,374 | 0.187 | 0.115 | 2 of 2 |

In this pilot, adding PUCCSD repetitions improved the observed energy accuracy while increasing the number of parameters and CX gates. The pilot is small: two starts per setting are not enough to establish a statistical guarantee or prove that any result is a global optimum.

### Best logged PUCCSD×3 result

A separate PUCCSD×3 optimization run reported:

| Quantity | Value |
|---|---:|
| Ansatz energy | −74.860975578262 Ha |
| Frozen-core CASCI energy | −74.860977098519 Ha |
| Absolute difference | 0.001520 mHa |
| Parameter count | 90 |
| Objective evaluation budget | 1,500 |
| Threshold comparison | Within 1.6 mHa |

This is the best energy value in the run output shared for this project. The run used the full evaluation budget. It should therefore be described as a **best observed, budget-limited result**. It does not prove optimizer convergence or a global optimum.

The resource pilot also reported a separate PUCCSD×3 run with an error of 0.115 mHa. It used a different run and should not be conflated with the best logged value above.

## Three-point asymmetric bond scan

A warm-start PUCCSD×3 scan was run at three values of \(R_2\). At each geometry, the optimized parameters from the previous geometry were used as the starting point for the next calculation.

| \(R_2\) (Å) | CASCI energy (Ha) | PUCCSD×3 energy (Ha) | Absolute difference (mHa) |
|---:|---:|---:|---:|
| 1.80 | −74.887678538893 | −74.887280139717 | 0.398 |
| 2.20 | −74.860977098519 | −74.860687456423 | 0.290 |
| 2.60 | −74.853880734062 | −74.853326368035 | 0.554 |

All three reported PUCCSD×3 energies are within 1.6 mHa of their corresponding CASCI references. This is a three-point scan, not a dense potential-energy curve.

A separate full-FCI value reported for \(R_2=2.60\) Å conflicts with a later reference-only calculation. That disputed value is excluded from this table and should not be used until the discrepancy is resolved from the saved output files.

## Optimizer comparison

We also compared optimizers for PUCCSD×1. The archived held-out summary reports the following median absolute errors relative to CASCI:

| Optimizer | Median absolute error (mHa) |
|---|---:|
| L-BFGS-B | 8.518 |
| SLSQP | 8.534 |
| COBYLA | 9.574 |
| SPSA, selected schedule | 106.586 |
| Powell | 273.682 |

These results apply only to the tested PUCCSD×1 circuit, initialization procedure, seeds, hyperparameters, and evaluation budget. They do not establish a general ranking of optimizers.

An objective-evaluation count is not the same thing as wall-clock time, gradient cost, quantum shot cost, or hardware workload. In particular, analytic gradients in a noiseless simulator do not imply the same cost on a quantum processor.

## Fermionic ADAPT-VQE

The adaptive calculation began from the Hartree–Fock reference and selected excitations from a fermionic UCCSD pool. At each macrocycle, it evaluated pool gradients, selected an operator, appended it to the circuit, and reoptimized the active parameters.

The final run requested 16 macrocycles, but the shared log contains completed results only through macrocycle 11. The last recorded energy was −74.857504538 Ha, which is **3.473 mHa above CASCI**.

| Completed macrocycle | Energy (Ha) | Absolute CASCI error (mHa) |
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

The recorded sequence lowered the energy over the completed cycles, but the run did not reach the 1.6 mHa threshold. Since cycles 12 through 16 are not present in the shared log, no result is claimed for them.

## Finite-shot local simulator result

A separate local Aer run evaluated a fixed PUCCSD×1 state using finite shots. The supplied run record reports 16 shots per each of 276 qubit-wise-commuting measurement groups, or 4,416 nominal shots in total, with one simulator seed.

| Quantity | Reported value |
|---|---:|
| Energy estimate | −74.071666227 Ha |
| Difference from CASCI | +789.311 mHa |
| Reported standard error | 570.414 mHa |
| Nominal shots | 4,416 |
| Independent simulator seeds | 1 |

This example is too statistically imprecise to support an accuracy claim. It is a local finite-shot simulation, not an IBM hardware result. The noise model and its parameters should be reported from the saved run configuration before this result is used to compare specific noise channels.

## IBM Quantum hardware measurements

### What the hardware jobs measured

All four IBM jobs measured the **Hartree–Fock reference state**. The circuit prepared that computational-basis state with four X gates and zero entangling gates.

The jobs did not use the optimized PUCCSD parameters. The PUCCSD×3 circuit, which has an estimated 1,374 logical CX gates, was not run on hardware.

Jobs B, C, and D used the 79 Z-only terms of the mapped Hamiltonian. For the ideal computational-basis Hartree–Fock state, terms containing X or Y have zero expectation. The shared simulation check found that the Z-only observable and the full Hamiltonian give the same ideal Hartree–Fock energy to within \(10^{-9}\) Ha.

### Hardware setup

| Item | Recorded setup |
|---|---|
| IBM backend | `ibm_kingston`, 156 qubits |
| Calibration snapshot | 2026-10-24 20:25 UTC |
| Runtime primitive | Qiskit Runtime EstimatorV2 |
| Software versions | Qiskit 1.4.3, qiskit-ibm-runtime 0.40.1, qiskit-nature 0.7.2 |
| Molecule and basis | H₂O, STO-3G |
| Geometry | \(R_1=0.96\) Å, \(R_2=2.20\) Å, \(\angle\mathrm{HOH}=104.5^\circ\) |
| Active space | CAS(8e,6o), oxygen 1s frozen |
| Mapping and reduction | ParityMapper with two-qubit reduction |
| Mapped problem size | 10 qubits |
| State measured | Hartree–Fock reference state |
| HF preparation circuit | Four X gates, zero entangling gates |

### Hardware job results

The total energies below include the molecular Hamiltonian constant. Offsets are calculated relative to the ideal Hartree–Fock energy, −74.623892 Ha. The reported standard errors are statistical estimates; they do not include every systematic hardware error.

| Job | IBM job ID | Observable and settings | Energy (Ha) | Reported standard error (mHa) | Offset from ideal HF (mHa) |
|---|---|---|---:|---:|---:|
| A | `dbehvvfgdj9s73flrceg` | Full 1,079-term Hamiltonian; 276 groups; resilience level 1; target precision 0.04 Ha | −73.967321 | 346.52 | +656.571 |
| B | `dbei45vpc3tc739lomf0` | 79 Z-only terms; one group; resilience level 1 with TREX and twirling; target 0.005 Ha | −74.542299 | 2,140.26 | +81.593 |
| C | `dbei5tvpc3tc739lop2g` | 79 Z-only terms; resilience level 0; 100,000 shots requested | −74.327453 | 3.45 | +296.439 |
| D | `dbei8tom94ac738rsp90` | 79 Z-only terms; resilience level 0; 100,000 shots requested; low-readout-error qubit layout | −74.573420 | 1.47 | +50.472 |

Job A took 104 seconds wall time. Job B used about 21 seconds of QPU time, with 40,000 service shots and 32 randomizations. It did not reach its requested 5 mHa precision. Runtime information for Jobs C and D was not supplied.

For Job D, the selected qubits were 148, 42, 117, 149, 154, 44, 91, 134, 40, and 89. Their estimated mean readout error was 0.00310, compared with 0.02016 for the device-wide mean in the calibration data used for that run.

### What these hardware results do and do not show

The four jobs show that the Hartree–Fock reference circuit and mapped observables were submitted to and evaluated by IBM hardware. They exercise Hamiltonian construction, mapping, transpilation, observable layout, and EstimatorV2 execution.

They do not show that VQE was optimized on the QPU. They do not measure the PUCCSD ansatz. They do not establish chemical accuracy on hardware.

Job B’s observed energy was closer to ideal HF than Job C’s, but its reported standard error was 2,140.26 mHa. These results do not establish a statistically reliable improvement from mitigation. Job D had a smaller observed offset and standard error than Job C in these individual jobs, but a single pair of executions does not establish a general benefit from low-readout-error qubit selection.

The cause of Job C’s large offset has not been independently verified. Readout error is a possible contributor, not a confirmed diagnosis. All reported standard errors are statistical only.

## Figures

The README can show key figures once their image files are added to the repository. Copy the prepared PNG figures into `results/publication_figures/` and use or adjust these links to match their actual filenames.

![PUCCSD accuracy and estimated CX resources](results/publication_figures/fig_accuracy_vs_resources.png)

*Energy error and estimated level-3 CX count for the ansatz resource pilot. The pilot used two starts per setting.*

![PUCCSD asymmetric bond scan](results/publication_figures/fig_asymmetric_bond_scan.png)

*Three-point warm-start scan. Errors are relative to frozen-core CASCI at each geometry.*

![ADAPT-VQE convergence](results/publication_figures/fig_adapt_convergence.png)

*Recorded ADAPT-VQE energy error through the 11 completed macrocycles available in the shared log.*

![IBM Hartree–Fock measurements](results/publication_figures/fig_hardware_hf_measurements.png)

*IBM measurements of the fixed Hartree–Fock reference state. The error bars are the reported statistical standard errors. These are not VQE-state measurements.*

Use the figure captions to preserve the distinction between noiseless simulation, local finite-shot simulation, and hardware measurement. Do not crop error bars or omit the large uncertainties from Jobs A and B.

## Reproducing the calculations

The project includes a Python package, experiment scripts, and a notebook. The following commands assume Linux, WSL, or Colab.

### Install

```bash
git clone https://github.com/Athleity/Quanta-H2O_VQE-.git
cd Quanta-H2O_VQE-
python -m pip install --prefer-binary -e .
```

For the documented WSL dependency set, use:

```bash
python -m pip install --prefer-binary -r config/requirements/requirements-wsl.txt
```

For local Aer noise simulation, install the additional noise dependencies:

```bash
python -m pip install --prefer-binary -r config/requirements/requirements-noise.txt
```

PySCF is intended to run in Linux, WSL, or Colab. A native Windows Python installation may require a separate supported environment.

### Calculate the reference energies

```bash
h2o-vqe \
  --reference-only \
  --stretched-oh 2.20 \
  --output results/references/reproduce-r2.20
```

### Run a PUCCSD×3 statevector calculation

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

Reproducing a published result exactly may require the same package versions, random seeds, optimizer configuration, and evaluation budget as the original run. An optimizer may stop at a different point even when the model and ansatz are unchanged.

### Run the asymmetric scan

```bash
h2o-vqe \
  --methods puccsd \
  --ansatz-reps 3 \
  --optimizer slsqp \
  --restarts 1 \
  --scan-r2 1.8,2.2,2.6 \
  --warm-start-scan \
  --output results/scans/reproduce-puccsd3-scan
```

### Run the notebook

Open `notebooks/h2o_asymmetric_stretch.ipynb` in Jupyter or Colab and run its setup cell before the calculation cells. The notebook is the interactive route through the project; the command-line interface is useful for repeatable parameterized runs.

Never put IBM API keys or account credentials in a notebook committed to a public repository. Use the notebook platform’s secret manager or enter credentials at runtime.

## Project files

| Path | Purpose |
|---|---|
| `README.md` | Project overview, results, hardware evidence, and reproduction instructions |
| `pyproject.toml` | Package metadata, dependencies, and command-line entry point |
| `src/h2o_vqe/` | Maintained chemistry, VQE, and noise implementation |
| `scripts/` | Experiment runners and figure-generation utilities |
| `notebooks/` | Interactive project notebook |
| `docs/` | Research notes and project documentation |
| `config/requirements/` | Environment-specific dependency lists |
| `results/` | Saved reference data, experiment outputs, and figures |
| `tests/` | Project checks |

## Team

**Team name:** Quanta  
**Submission category:** VQE for Chemistry & Materials

| Member | Institution | Department or field | Career level |
|---|---|---|---|
| Priyansh Bhavsar | IIT Jodhpur | Physics | Bachelor’s student |
| Mohammed Hasan Iqbal | IIT Bombay | Physics | Student |
| Yahya Mohammed | Nile University | Computer Science | Student |
| Donia Mohammed | Zagazig University | Chemistry and Computer Science | Student |

## Limitations and interpretation

* The calculations use the STO-3G basis and frozen-core CAS(8e,6o). Results apply to this model and do not represent a complete-basis-set exact energy for water.
* Full STO-3G FCI and frozen-core CASCI use different configuration spaces. VQE errors in this project are measured against CASCI.
* The bond scan contains three geometries. It is not a densely sampled potential-energy curve.
* The ansatz resource pilot used two starts per setting and a finite evaluation cap.
* The best logged PUCCSD×3 run reached its 1,500 evaluation budget. Its energy is a best observed value, not evidence of a global optimum.
* The optimizer comparison applies to the tested PUCCSD×1 setup and its recorded settings. It is not a universal optimizer ranking.
* The level-3 CX counts are logical transpilation estimates. They are not hardware-routed PUCCSD gate counts.
* The shared ADAPT log records 11 completed macrocycles from a 16-cycle request.
* The local finite-shot result has one seed and a large reported uncertainty.
* IBM hardware jobs measured the Hartree–Fock reference state, not an optimized VQE state.
* Hardware standard errors are statistical estimates and do not capture every systematic device effect.
* No VQE parameter optimization was performed on IBM hardware.
* A noisy estimate below a reference energy is not, by itself, evidence of a better variational state. Compare uncertainty, bias, and the ideal reference carefully.

## References

1. Bian et al., “Quantum computing methods for electronic states of the water molecule,” *Molecular Physics* (2019). [arXiv:1804.05453](https://arxiv.org/abs/1804.05453)
2. Lee et al., “Generalized Unitary Coupled Cluster Wavefunctions for Quantum Computation,” *Journal of Chemical Theory and Computation* 15, 311–324 (2019). [DOI: 10.1021/acs.jctc.8b01004](https://doi.org/10.1021/acs.jctc.8b01004)
3. Grimsley et al., “An adaptive variational algorithm for exact molecular simulations on a quantum computer,” *Nature Communications* 10, 3007 (2019). [DOI: 10.1038/s41467-019-10988-2](https://doi.org/10.1038/s41467-019-10988-2)
4. Qiskit Nature, [PUCCSD API](https://qiskit-community.github.io/qiskit-nature/stubs/qiskit_nature.second_q.circuit.library.PUCCSD.html), [VQE with UCC](https://qiskit-community.github.io/qiskit-nature/howtos/vqe_ucc.html), and [ADAPT-VQE guide](https://qiskit-community.github.io/qiskit-nature/howtos/adapt_vqe.html).
5. The expanded literature review and source notes are in [`docs/RESEARCH.md`](docs/RESEARCH.md).
