#!/usr/bin/env bash
# INSTALL COMMAND (Quanta VQE)
# From the repository root, install dependencies with:
# python -m pip install --prefer-binary -r config/requirements/requirements-backend-noise.txt

# Local Aer study using the selected IBM backend's calibration snapshot.
# This fetches backend metadata but does not submit a QPU job.
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-1}"

# Keep an explicitly activated isolated noise environment. Fall back to the
# project's main environment only when the caller has not selected one.
if [[ -z "${VIRTUAL_ENV:-}" && -f "$HOME/venvs/h2o-vqe/bin/activate" ]]; then
  source "$HOME/venvs/h2o-vqe/bin/activate"
fi

backend_args=()
if [[ -n "${H2O_FAKE_BACKEND:-}" && -n "${H2O_IBM_BACKEND:-}" ]]; then
  echo "Set only one of H2O_FAKE_BACKEND or H2O_IBM_BACKEND." >&2
  exit 2
elif [[ -n "${H2O_FAKE_BACKEND:-}" ]]; then
  backend_args=(--fake-backend "$H2O_FAKE_BACKEND")
elif [[ -n "${H2O_IBM_BACKEND:-}" ]]; then
  backend_args=(--backend "$H2O_IBM_BACKEND")
else
  echo "Set H2O_FAKE_BACKEND (offline snapshot, e.g. fake_brisbane) or H2O_IBM_BACKEND (live calibration read)." >&2
  exit 2
fi

if ! command -v h2o-vqe-backend-noise >/dev/null 2>&1; then
  echo "Missing h2o-vqe-backend-noise entry point. Reinstall in the active venv with: python -m pip install --prefer-binary -e \".[backend-noise]\"" >&2
  exit 2
fi

h2o-vqe-backend-noise \
  "${backend_args[@]}" \
  --shots-per-group "${H2O_NOISE_SHOTS_PER_GROUP:-1024}" \
  --group-batch-size "${H2O_NOISE_GROUP_BATCH_SIZE:-12}" \
  --seeds "${H2O_NOISE_SEEDS:-11,29,47}" \
  --cases "${H2O_NOISE_CASES:-puccsd_reps1,puccsd_reps3}" \
  --output "${H2O_BACKEND_NOISE_OUTPUT:-results/backend-noise-study}" \
  2>&1 | tee "${H2O_BACKEND_NOISE_LOG:-results/backend-noise-study.log}"
