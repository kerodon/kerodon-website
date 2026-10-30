"""Regression coverage for isolated performance benchmarks."""

import runpy
import tempfile
import unittest
from pathlib import Path


class BenchmarkTests(unittest.TestCase):
    def test_snapshot_preserves_all_templates(self):
        root = Path(__file__).resolve().parents[2]
        snapshot_code = runpy.run_path(
            str(Path(__file__).with_name("benchmark_comparison.py")))["snapshot_code"]
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            snapshot_code(root, destination)
            for source in (root / "gerby/templates").rglob("*"):
                if source.is_file():
                    with self.subTest(template=source.name):
                        self.assertEqual(source.read_bytes(),
                                         (destination / source.relative_to(root)).read_bytes())


if __name__ == "__main__":
    unittest.main()
