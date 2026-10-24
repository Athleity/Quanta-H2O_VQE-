#!/usr/bin/env bash
# Sequential, fixed-parameter finite-shot noise comparison for existing H2O runs.
# This intentionally does not optimize under noise and does not claim hardware results.
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Avoid launching additional BLAS/OpenMP worker pools alongside quantum simulation.
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-1}"

if [[ -f "$HOME/venvs/h2o-vqe/bin/activate" ]]; then
  # The project documents this WSL virtual environment; activate it when present.
  source "$HOME/venvs/h2o-vqe/bin/activate"
fi

if ! python -c 'import qiskit_aer' >/dev/null 2>&1; then
  echo "Qiskit Aer is required. Install it with: python -m pip install --prefer-binary -r config/requirements/requirements-noise.txt" >&2
  exit 2
fi

# These are the actual completed result directories used for the pilot comparison.
# Validate all inputs before spending time on any noisy circuit evaluations.
labels=(uccsd_reps1 puccsd_reps1 puccsd_reps2 puccsd_reps3)
methods=(uccsd puccsd puccsd puccsd)
run_dirs=(
  "results/ansatz/uccsd-slsqp100-updated"
  "results/ansatz/puccsd-slsqp-restarts3-100"
  "results/ansatz/puccsd-reps2-slsqp100"
  "results/optimizers/puccsd3-extra-slsqp-seed20261024"
)
for run_dir in "${run_dirs[@]}"; do
  for metadata in summary.json reference.json; do
    if [[ ! -s "$run_dir/$metadata" ]]; then
      echo "Missing required saved result: $run_dir/$metadata" >&2
      exit 2
    fi
  done
done

shots="${H2O_NOISE_SHOTS:-1000}"
seeds="${H2O_NOISE_SEEDS:-11,29,47}"
p1="${H2O_ONE_QUBIT_DEPOL:-1e-4}"
p2="${H2O_TWO_QUBIT_DEPOL:-1e-3}"
readout="${H2O_READOUT_ERROR:-0.01}"
output_dir="results/noise-ansatz-study"
mkdir -p "$output_dir"

for i in "${!labels[@]}"; do
  label="${labels[$i]}"
  run_dir="${run_dirs[$i]}"
  method="${methods[$i]}"
  echo "[$label] fixed-circuit noise estimate; shots/group=$shots; seeds=$seeds"
  python -u scripts/compat/noisy_energy.py "$run_dir" \
    --methods "$method" \
    --shots "$shots" \
    --seeds "$seeds" \
    --one-qubit-depol "$p1" \
    --two-qubit-depol "$p2" \
    --readout-error "$readout" \
    --output "$output_dir/$label.json" \
    2>&1 | tee "$output_dir/$label.log"
done

echo "Noise comparison complete. JSON and logs are in $output_dir/"
