"""Compatibility CLI for the H₂O VQE engine.

Implementation lives in ``src/h2o_vqe/engine.py``. Keep this small compatibility launcher
so documented WSL commands and existing saved scripts remain valid.
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from h2o_vqe.engine import (  # noqa: E402
    Geometry,
    _require_scientific_stack,
    build_active_problem,
    main,
)

if __name__ == "__main__":
    raise SystemExit(main())