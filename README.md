# Quanta H₂O VQE
## Asymmetric O–H bond stretching with chemistry-inspired ansätze

**Submission category:** VQE for Chemistry & Materials  
**Scientific question:** How do chemistry-inspired variational ansätze trade energy accuracy against circuit resources for stretched water?  
**Molecular model:** H₂O in STO-3G; H–O–H angle fixed at 104.5°; one O–H bond fixed at 0.96 Å; second O–H distance R₂ varied. Main comparison: R₂ = 2.20 Å.  
**Project/team label:** Quanta (confirm the official team name before submission).

> **Read this distinction first:** the best VQE accuracy reported below is from a noiseless classical statevector simulation. The IBM jobs measured the Hartree–Fock reference state only. They did not measure the PUCCSD circuit, did not optimize VQE parameters on hardware, and do not demonstrate chemical accuracy on hardware.

## Project overview

This project builds an H₂O electronic-structure problem from its geometry, checks the active-space Hamiltonian against independent classical references, and studies variational quantum eigensolver (VQE) ansätze for an asymmetric O–H stretch. It compares UCCSD, paired UCCSD (PUCCSD), and fermionic ADAPT-VQE in noiseless simulation, then measures the fixed Hartree–Fock (HF) reference state on IBM hardware.

The work is organized around three distinct kinds of evidence:

1. **Classical references:** RHF, frozen-core CASCI, all-electron STO-3G FCI, and an independent exact solve of the mapped active-space Hamiltonian.
2. **Noiseless VQE simulation:** ansatz/optimizer comparisons and a three-geometry scan, scored against frozen-core CASCI.
3. **IBM hardware measurement:** four fixed-state measurements of the HF reference. These validate the execution pipeline; they are not VQE results.

## Headline results

At R₂ = 2.20 Å, the frozen-core CASCI(8e,6o) reference is **−74.860977098519 Ha**. The independent exact diagonalization of the mapped active-space Hamiltonian agrees with this value. VQE errors in this project are measured relative to active-space CASCI; the chemical-accuracy threshold used here is **1.6 mHa**.

The best archived noiseless VQE simulation is **PUCCSD ×3 at −74.860885521062 Ha**, approximately **0.092 mHa** above CASCI. This is a classical statevector result.

On IBM hardware, the measured state was the HF reference, whose ideal energy is **−74.623892 Ha**. The four measured energies ranged from **−74.573420 Ha** to **−73.967321 Ha**. Their measured offsets from ideal HF ranged from **+50.472 mHa** to **+656.571 mHa**. Job B’s reported standard error was **2,140.26 mHa**; it did not reach its 5 mHa precision target. None of these jobs measured a VQE-optimized state or established chemical accuracy.

## Scientific model and reference energies

### Molecular geometry and active space

The primary geometry is defined by O(0,0,0), H(0,0,0.96 Å), and a second H at the chosen R₂ and fixed angle:

```text
O  0.0  0.0  0.0
H  0.0  0.0  0.96
H  R₂ sin(104.5°)  0.0  R₂ cos(104.5°)
```

The electronic-structure calculation uses STO-3G and a frozen-core CAS(8e,6o), with the oxygen 1s orbital frozen. The active space contains 12 spin orbitals and is mapped to 10 qubits using the ParityMapper with two-qubit reduction. The molecular Hamiltonian is generated from the specified molecular geometry; it is not a manually typed Pauli Hamiltonian.

### Reference energies at R₂ = 2.20 Å

| Reference | Energy (Ha) | Use |
|---|---:|---|
| RHF | −74.623892380736 | Ideal HF reference-state energy |
| Frozen-core CASCI(8e,6o) | −74.860977098519 | Active-space target for VQE errors |
| Full STO-3G FCI | −74.861014224915 | Separate all-electron STO-3G reference |
| Mapped active-space exact solve | −74.860977098519 | Independent exact check; agrees with CASCI |

Full STO-3G FCI and frozen-core active-space CASCI are distinct calculations. VQE errors and chemical-accuracy claims in this repository use CASCI, not full-system FCI. The ideal HF state is approximately **237.085 mHa above CASCI**.

## Noiseless VQE workflow and results

1. PySCF builds H₂O at the selected geometry and computes RHF, all-electron STO-3G FCI, and frozen-core CASCI.
2. The CAS(8e,6o) active-space Hamiltonian is mapped to 10 qubits and checked by independent exact diagonalization.
3. The mapped active-space HF state initializes the variational circuits.
4. Classical optimizers minimize statevector expectation values. Saved results include energies, parameters, optimization histories, and circuit-resource metrics where available.
5. VQE errors are calculated against active-space CASCI.

### Matched ansatz pilot at R₂ = 2.20 Å

The pilot used two starts per setting and a cap of 150 objective evaluations. CX counts below are level-3 logical-circuit transpilation estimates, not hardware-routed gate counts.

| Ansatz | Parameters | Level-3 CX estimate | Median CASCI error (mHa) | Best observed error (mHa) | Starts within 1.6 mHa |
|---|---:|---:|---:|---:|---:|
| UCCSD ×1 | 92 | 1,955 | 7.193 | 0.064 | 1/2 |
| PUCCSD ×1 | 30 | 458 | 8.524 | 8.518 | 0/2 |
| PUCCSD ×2 | 60 | 916 | 2.876 | 2.517 | 0/2 |
| PUCCSD ×3 | 90 | 1,374 | 0.187 | 0.115 | 2/2 |

These are small, budget-capped samples. Two starts per configuration do not establish a statistical guarantee or a global optimum. A separate completed PUCCSD ×3 SLSQP run reached **−74.860885521062 Ha**, about **0.092 mHa** above CASCI. Its 90-parameter vector is saved at `results/ansatz/puccsd3_params.json`.

### Bond scan and optimizer study

A warm-start PUCCSD ×3 scan produced absolute CASCI errors of **0.398, 0.290, and 0.554 mHa** at R₂ = 1.80, 2.20, and 2.60 Å. This is a three-point scan, not a dense or interpolated potential-energy curve. At R₂ = 2.60 Å, full STO-3G FCI and frozen-core CASCI differ by about 2.026 mHa; they must not be treated as interchangeable.

The held-out optimizer comparison is for PUCCSD ×1 only:

| Optimizer | Median absolute error vs CASCI (mHa) |
|---|---:|
| L-BFGS-B | 8.518 |
| SLSQP | 8.534 |
| COBYLA | 9.574 |
| SPSA (selected schedule) | 106.586 |
| Powell | 273.682 |

This result applies only to the archived ansatz, seeds, settings, and budget. It is not a universal optimizer ranking. Objective-evaluation counts do not equate to wall-clock time, gradient cost, shot cost, or hardware workload.

### Fermionic ADAPT-VQE

The run requested 16 macrocycles but the archive contains progress only through cycle 11. The last recorded error is **3.473 mHa**, so the recorded run is incomplete and did not reach the 1.6 mHa threshold. The remaining five cycles are unobserved.

### Synthetic finite-shot simulator example

A separate local simulation used PUCCSD ×1, 16 shots per each of 276 qubit-wise-commuting groups (4,416 nominal shots total), one seed, and synthetic noise parameters p₁ = 10⁻⁴, p₂ = 10⁻³, and symmetric readout flip 1%. The noisy estimate differed from CASCI by **+789.3 mHa**, with a propagated standard error of **570.4 mHa**. This is a low-precision synthetic simulation example, not IBM-calibrated noise and not hardware data.

## IBM hardware measurement

### What was run

All four IBM jobs measured the **HF reference state only**. The circuit has four X gates and zero entangling gates. It is not the PUCCSD or VQE-optimized state. The approximately 1,374-CX PUCCSD ×3 circuit was not run on hardware.

Jobs B–D measured the 79 Z-only terms of the mapped Hamiltonian. For the computational-basis HF state, terms containing X or Y have zero ideal expectation. A simulator check found the ideal Z-only energy equal to the full HF energy within 10⁻⁹ Ha.

### Hardware environment

| Item | Recorded value |
|---|---|
| Backend | IBM `ibm_kingston`, 156 qubits |
| Calibration snapshot | 2026-10-24 20:25 UTC |
| Runtime primitive | Qiskit Runtime EstimatorV2 |
| Software | Qiskit 1.4.3; qiskit-ibm-runtime 0.40.1; qiskit-nature 0.7.2 |
| Molecule and basis | H₂O, STO-3G |
| Geometry | R₂ = 2.20 Å; R₁ = 0.96 Å; ∠HOH = 104.5° |
| Active space | CAS(8e,6o), oxygen 1s frozen |
| Mapping | ParityMapper with two-qubit reduction; 10 qubits |
| Measured state | HF reference; 4 X gates; 0 entangling gates |

### Job results

Total energies include the molecular Hamiltonian’s constant shift. Offset from ideal HF is computed against **−74.623892 Ha**. Reported standard errors are statistical; they do not account for all systematic device error.

| Job | IBM job ID | Observable and run settings | Total energy (Ha) | Reported standard error | Offset from ideal HF |
|---|---|---|---:|---:|---:|
| A | `dbehvvfgdj9s73flrceg` | Full 1,079-term Hamiltonian; 276 groups; resilience level 1; target precision 0.04 Ha | −73.967321 | 346.52 mHa | +656.571 mHa |
| B | `dbei45vpc3tc739lomf0` | 79 Z-only terms; one group; resilience level 1 with TREX and twirling; target 0.005 Ha; 40,000 service shots and 32 randomizations | −74.542299 | 2,140.26 mHa | +81.593 mHa |
| C | `dbei5tvpc3tc739lop2g` | Same Z-only observable; resilience level 0; 100,000 shots requested | −74.327453 | 3.45 mHa | +296.439 mHa |
| D | `dbei8tom94ac738rsp90` | Same Z-only observable; resilience level 0; 100,000 shots requested; layout selected low-readout-error qubits | −74.573420 | 1.47 mHa | +50.472 mHa |

Job A took 104 seconds wall time. Job B used about 21 seconds of QPU time and did not reach its 5 mHa precision target. Runtime values for Jobs C and D were not supplied.

### Hardware observations and limits

- The jobs demonstrate real hardware execution of the fixed HF circuit through Hamiltonian construction, mapping, transpilation, observable layout, and EstimatorV2 submission.
- Job B’s observed offset (+81.593 mHa) was smaller than Job C’s (+296.439 mHa), but Job B’s reported standard error was very large (+/−2,140.26 mHa). This single measurement does not establish a statistically reliable mitigation improvement.
- Job D used qubits 148, 42, 117, 149, 154, 44, 91, 134, 40, and 89. Their mean estimated readout error was 0.00310; the device-wide mean was 0.02016. Job D’s measured offset was +50.472 mHa with 1.47 mHa reported statistical standard error. This is an observation for one job and layout, not a general device-performance claim.
- Job C’s large offset may be consistent with systematic error such as readout error, but the cause was not independently verified.
- No hardware job measured PUCCSD or a VQE-optimized state. None of the hardware results demonstrates chemical accuracy.
- The reported standard errors are statistical only.

The hardware job data supplied for this report should be archived in `results/hardware/` with non-secret metadata. Never commit IBM API keys, tokens, or private account information.

## Figures and archived data

The publication figures are generated from archived CSV and JSON outputs using `scripts/make_publication_figures.py`. Editable SVGs, PNG previews, the gallery, source manifest, and figure captions are in `results/publication_figures/`. Interpret every figure together with its caption, source, and sample size. The ansatz pilot has two starts per setting; the ADAPT trace is incomplete; the synthetic noise example has large uncertainty.

Main data sources:

- `results/references/` — RHF, FCI, CASCI, mapped exact checks, and orbital audit.
- `results/ansatz/ansatz-resource-pilot/ansatz_runs.csv` — ansatz pilot metrics.
- `results/scans/puccsd-reps3-scan/asymmetric_stretch_scan.csv` — three-point warm-start scan.
- `results/optimizers/systematic-optimizer-study/` — tuning, held-out runs, and checkpoints.
- `results/ansatz/adapt-slsqp-final-16cycle/adapt_progress.csv` — archived partial ADAPT progress.
- `results/noisy-demo/puccsd-reps1-16shots.json` — synthetic finite-shot simulation.
- `results/hardware/` — IBM hardware records.

The hardware comparison figure should display total energies in Ha and reference lines for ideal HF and CASCI. Because Jobs A and B have large reported standard errors, show those uncertainties without clipping or implying that their estimates are precise. A separate uncertainty panel or inset is needed so Jobs C and D remain legible.

## Reproduction

### Install

The maintained package declares its dependencies in `pyproject.toml`. In Colab or Linux/WSL:

```bash
git clone https://github.com/Athleity/Quanta-H2O_VQE-.git
cd Quanta-H2O_VQE-
python -m pip install --prefer-binary -e .
```

For the core WSL environment:

```bash
python -m pip install --prefer-binary -r config/requirements/requirements-wsl.txt
```

PySCF is intended to run in Linux, WSL, or Colab rather than a native Windows Python environment.

### Run a reference and VQE calculation

```bash
h2o-vqe --reference-only --stretched-oh 2.20 --output results/references/reproduce-r2.20
h2o-vqe --methods puccsd --ansatz-reps 3 --optimizer slsqp \
  --restarts 1 --seed 20261023 --maxiter 100 \
  --output results/ansatz/reproduce-puccsd3-r2.20
```

Regenerate figures from saved data:

```bash
python scripts/make_publication_figures.py
```

The runnable project workflow is in `notebooks/h2o_asymmetric_stretch.ipynb`. The maintained VQE implementation is in `src/h2o_vqe/engine.py`; `scripts/compat/h2o_vqe.py` is a compatibility launcher. The IBM workflow is separate and evaluates a fixed saved state; it does not optimize parameters on the QPU.

## Repository map

```text
README.md                         project overview and results narrative
pyproject.toml                    package metadata and CLI entry point
src/h2o_vqe/                      maintained chemistry, VQE, noise, and IBM code
scripts/                          experiment workflows and figure generator
notebooks/                        runnable submission notebook
docs/                             research review and project-status snapshot
results/references/               RHF, FCI, CASCI, mapping, orbital checks
results/ansatz/                   ansatz studies and saved PUCCSD(3) parameters
results/scans/                    asymmetric O–H scan data
results/optimizers/               optimizer tuning and held-out comparison
results/noisy-demo/               synthetic finite-shot simulation
results/hardware/                 IBM job records and hardware report
results/publication_figures/      SVG figures, PNG previews, gallery, captions
tests/                             project checks
```

## Team

**Project/team label:** Quanta; confirm the official name with the team.  
**Submission category:** VQE for Chemistry & Materials.

| Member | Institution | Department / field | Career level |
|---|---|---|---|
| Priyansh Bhavsar | IIT Jodhpur | Physics | Bachelor’s student |
| Mohammed Hasan Iqbal | IIT Bombay | Not provided | Not provided |
| Yahya Mohammed | Nile University | Computer Science | Not provided |
| Donia Mohammed | Zagazig University | Chemistry and Computer Science | Not provided |

Unknown affiliations and career levels are marked “Not provided”; confirm them with the members rather than guessing.

## Limitations

- STO-3G and frozen-core CAS(8e,6o) are model choices; CASCI is not the complete-basis-set exact ground energy of water.
- Full STO-3G FCI and frozen-core CASCI are different references. VQE error claims here use CASCI.
- The geometry scan has three points only.
- The matched ansatz pilot has two starts per setting and a finite evaluation cap.
- The optimizer comparison applies only to the tested PUCCSD ×1 setup and settings.
- Transpiled CX counts are logical-circuit estimates, not hardware-routed counts for the VQE ansätze.
- ADAPT-VQE progress is archived for 11 of 16 requested cycles.
- The low-shot noisy simulator example is statistically imprecise and is not a QPU measurement.
- IBM hardware measurements are of the HF state only. Their reported standard errors are statistical and do not capture all device systematics.
- No VQE parameter optimization was performed on IBM hardware.
- Never interpret a noisy estimate below a reference as a variational improvement without an uncertainty-aware analysis.

## References

The broader literature review is in [docs/RESEARCH.md](docs/RESEARCH.md).

- Bian et al., [Quantum computing methods for electronic states of the water molecule](https://arxiv.org/abs/1804.05453), *Molecular Physics* (2019).
- Lee et al., [Generalized Unitary Coupled Cluster Wavefunctions for Quantum Computation](https://doi.org/10.1021/acs.jctc.8b01004), *Journal of Chemical Theory and Computation* 15, 311–324 (2019). The project uses the Qiskit PUCCSD ansatz; this name does not imply equivalence to every k-UpCCGSD implementation.
- Grimsley et al., [An adaptive variational algorithm for exact molecular simulations on a quantum computer](https://doi.org/10.1038/s41467-019-10988-2), *Nature Communications* 10, 3007 (2019).
- [Qiskit Nature PUCCSD API](https://qiskit-community.github.io/qiskit-nature/stubs/qiskit_nature.second_q.circuit.library.PUCCSD.html), [UCC/VQE guide](https://qiskit-community.github.io/qiskit-nature/howtos/vqe_ucc.html), and [ADAPT-VQE guide](https://qiskit-community.github.io/qiskit-nature/howtos/adapt_vqe.html).
- Nature, [Preparing figures: specifications and accessibility](https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/).

