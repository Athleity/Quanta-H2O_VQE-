"""Compatibility CLI for finite-shot evaluation of saved VQE parameters."""
# INSTALL COMMAND (Quanta VQE)
# From the repository root, install dependencies with:
# python -m pip install --prefer-binary -r config/requirements/requirements-noise.txt


from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from h2o_vqe.noise import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())