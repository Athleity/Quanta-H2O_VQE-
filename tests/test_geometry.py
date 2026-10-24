"""Dependency-light checks for the explicit H2O geometry construction."""

from __future__ import annotations

import math
import unittest
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from h2o_vqe.engine import Geometry


def parse_xyz(spec: str) -> list[tuple[str, tuple[float, float, float]]]:
    atoms = []
    for atom in spec.split(";"):
        fields = atom.split()
        atoms.append((fields[0], tuple(float(x) for x in fields[1:])))
    return atoms


def distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


class GeometryTests(unittest.TestCase):
    def test_default_geometry_preserves_bonds_and_angle(self) -> None:
        geometry = Geometry(0.96, 2.20, 104.5)
        oxygen, h1, h2 = [coords for _, coords in parse_xyz(geometry.pyscf_atom_spec())]
        self.assertAlmostEqual(distance(oxygen, h1), 0.96, places=10)
        self.assertAlmostEqual(distance(oxygen, h2), 2.20, places=10)
        dot = sum((a - o) * (b - o) for o, a, b in zip(oxygen, h1, h2))
        norm_product = distance(oxygen, h1) * distance(oxygen, h2)
        angle = math.degrees(math.acos(dot / norm_product))
        self.assertAlmostEqual(angle, 104.5, places=10)

    def test_rejects_nonphysical_input_ranges(self) -> None:
        for geometry in (
            Geometry(0.1, 2.2, 104.5),
            Geometry(0.96, 9.0, 104.5),
            Geometry(0.96, 2.2, 180.0),
        ):
            with self.subTest(geometry=geometry), self.assertRaises(ValueError):
                geometry.validate()


if __name__ == "__main__":
    unittest.main()
