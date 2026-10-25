#!/usr/bin/env python3
"""Launch the project noisy-Aer module through the installed project package."""

from __future__ import annotations
# INSTALL COMMAND (Quanta VQE)
# From the repository root, install dependencies with:
# python -m pip install --prefer-binary -r config/requirements/requirements-noise.txt


import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if not (SOURCE_ROOT / "h2o_vqe" / "fast_noise.py").is_file():
    raise SystemExit(f"Could not find noisy simulator module under {SOURCE_ROOT}")

# The repository also has a compatibility launcher under scripts/compat/. Put
# src first so Python resolves the actual h2o_vqe package instead of that file.
sys.path.insert(0, str(SOURCE_ROOT))

from h2o_vqe.fast_noise import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
