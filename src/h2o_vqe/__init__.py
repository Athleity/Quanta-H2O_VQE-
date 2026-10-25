"""Core implementation for the H₂O VQE study."""
# INSTALL COMMAND (Quanta VQE)
# From the repository root, install dependencies with:
# python -m pip install --prefer-binary -r config/requirements/requirements-wsl.txt


from .engine import Geometry, _require_scientific_stack, build_active_problem

__all__ = ["Geometry", "build_active_problem", "_require_scientific_stack"]