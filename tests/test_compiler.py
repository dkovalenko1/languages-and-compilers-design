"""Compile fixtures through the CLI, verify IR, and run native programs."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import src_path  # noqa: F401  (puts src/ on sys.path)
from llvmlite import binding as llvm
from lexer import CompileError


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests"


class CompilerTests(unittest.TestCase):
    def compile(self, source, output):
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "src" / "compiler.py"), str(source), str(output)],
            capture_output=True, text=True,
        )

    def test_valid_programs(self):
        clang = shutil.which("clang")
        if clang is None:
            raise AssertionError("clang is required for end-to-end tests")
        old_sources = sorted((FIXTURES / "valid").glob("*.txt"))
        new_sources = sorted((FIXTURES / "ok").glob("*.txt"))
        self.assertGreaterEqual(len(old_sources), 5)
        self.assertGreaterEqual(len(new_sources), 6)
        sources = old_sources + new_sources
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
                expected = source.with_suffix(".expected" if source.parent.name == "ok" else ".out")
                self.assertEqual(run.stdout, expected.read_text())

    def test_invalid_programs(self):
        old_sources = sorted((FIXTURES / "invalid").glob("*.txt"))
        new_sources = sorted((FIXTURES / "err").glob("*.txt"))
        self.assertGreaterEqual(len(old_sources), 5)
        self.assertGreaterEqual(len(new_sources), 6)
        sources = old_sources + new_sources
        for source in sources:
            with self.subTest(program=source.name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output.ll"
                result = self.compile(source, output)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                expected = source.with_suffix(".expected" if source.parent.name == "err" else ".err")
                self.assertEqual(result.stderr, expected.read_text())
                self.assertFalse(output.exists(), "Invalid input must not create an IR file")

    def test_error_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.ll"
            output.write_text("existing output\n")
            result = self.compile(FIXTURES / "invalid" / "const_assignment.txt", output)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_text(), "existing output\n")

    def test_semantic_error_precedes_codegen(self):
        from compiler import compile_program

        with patch("compiler.CodeGen") as generator:
            with self.assertRaises(CompileError):
                compile_program(b"bool b{1}\nexit b")
            generator.assert_not_called()

    def test_typed_ir_includes_widening_comparison_and_bool_select(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.ll"
            program = FIXTURES / "ok" / "mixed_integer_compare.txt"
            self.assertEqual(self.compile(program, output).returncode, 0)
            ir_text = output.read_text()
            self.assertIn("sext i32", ir_text)
            self.assertIn("icmp eq i64", ir_text)
            self.assertRegex(ir_text, r"select\s+i1")


if __name__ == "__main__":
    unittest.main()
