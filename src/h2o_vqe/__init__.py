"""Core implementation for the H₂O VQE study."""

from .engine import Geometry, _require_scientific_stack, build_active_problem

__all__ = ["Geometry", "build_active_problem", "_require_scientific_stack"]