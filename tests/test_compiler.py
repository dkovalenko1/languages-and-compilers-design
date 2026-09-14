"""Compile fixtures through the CLI, verify IR, and run native programs."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from llvmlite import binding as llvm


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests"


class CompilerTests(unittest.TestCase):
    def compile(self, source, output):
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "compiler.py"), str(source), str(output)],
            capture_output=True, text=True,
        )

    def test_valid_programs(self):
        clang = shutil.which("clang")
        if clang is None:
            raise AssertionError("clang is required for end-to-end tests")
        sources = sorted((FIXTURES / "valid").glob("*.txt"))
        self.assertGreaterEqual(len(sources), 5)
        for source in sources:
            with self.subTest(program=source.name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output.ll"
                result = self.compile(source, output)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(result.stdout, "")
                llvm.parse_assembly(output.read_text()).verify()
                program = Path(directory) / "program"
                linked = subprocess.run([clang, str(output), "-o", str(program)],
                                        capture_output=True, text=True)
                self.assertEqual(linked.returncode, 0, linked.stderr)
                run = subprocess.run([str(program)], capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(run.stderr, "")
                self.assertEqual(run.stdout, source.with_suffix(".out").read_text())

    def test_invalid_programs(self):
        sources = sorted((FIXTURES / "invalid").glob("*.txt"))
        self.assertGreaterEqual(len(sources), 5)
        for source in sources:
            with self.subTest(program=source.name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output.ll"
                result = self.compile(source, output)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, source.with_suffix(".err").read_text())
                self.assertFalse(output.exists(), "Invalid input must not create an IR file")

    def test_error_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.ll"
            output.write_text("existing output\n")
            result = self.compile(FIXTURES / "invalid" / "const_assignment.txt", output)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_text(), "existing output\n")


if __name__ == "__main__":
    unittest.main()
