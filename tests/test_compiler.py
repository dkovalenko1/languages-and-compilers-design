"""Compile fixtures through the CLI, verify IR, and run native programs."""

from pathlib import Path
import re
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
                run = subprocess.run([str(program)], capture_output=True, text=True, timeout=10)
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

    def compiled_ir(self, program):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.ll"
            result = self.compile(program, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            return output.read_text()

    def test_every_block_ends_once_and_slots_live_in_entry(self):
        terminators = {"br", "ret"}
        for source in sorted((FIXTURES / "ok").glob("*.txt")):
            with self.subTest(program=source.name):
                module = llvm.parse_assembly(self.compiled_ir(source))
                module.verify()
                main = module.get_function("main")
                for index, block in enumerate(main.blocks):
                    opcodes = [instruction.opcode for instruction in block.instructions]
                    self.assertIn(opcodes[-1], terminators, block.name)
                    self.assertEqual(sum(op in terminators for op in opcodes), 1, block.name)
                    if index > 0:
                        self.assertNotIn("alloca", opcodes, block.name)

    def test_nested_ifs_become_then_and_merge_blocks(self):
        module = llvm.parse_assembly(self.compiled_ir(FIXTURES / "ok" / "scope_warm-up.txt"))
        blocks = list(module.get_function("main").blocks)
        self.assertEqual([block.name for block in blocks],
                         ["entry", "then", "merge", "then.1", "merge.1"])
        allocas = [re.search(r"alloca (\w+)", str(i)).group(1)
                   for i in blocks[0].instructions if i.opcode == "alloca"]
        self.assertEqual(allocas, ["i32", "i1", "i64"])  # Three x, three slots.
        last = [list(block.instructions)[-1] for block in blocks]
        self.assertRegex(str(last[0]), r'br i1 (1|true), label %"?then"?, label %"?merge"?')
        self.assertRegex(str(last[1]), r'br i1 %\S+, label %"?then\.1"?, label %"?merge\.1"?')
        self.assertEqual([i.opcode for i in last[2:]], ["ret", "ret", "ret"])

    def test_if_else_branches_on_the_condition(self):
        ir_text = self.compiled_ir(FIXTURES / "ok" / "if-else_example.txt")
        self.assertRegex(ir_text, r'br i1 %"?\.?\w+"?, label %"then", label %"else"')
        self.assertEqual(ir_text.count('br label %"merge"'), 2)

    def test_while_has_condition_body_end_and_a_back_edge(self):
        module = llvm.parse_assembly(self.compiled_ir(FIXTURES / "ok" / "while_sum.txt"))
        blocks = {block.name: list(block.instructions) for block in module.get_function("main").blocks}
        self.assertEqual(list(blocks), ["entry", "cond", "body", "end"])
        self.assertRegex(str(blocks["entry"][-1]), r'br label %"?cond"?')
        self.assertRegex(str(blocks["cond"][-1]), r'br i1 %\S+, label %"?body"?, label %"?end"?')
        self.assertRegex(str(blocks["body"][-1]), r'br label %"?cond"?')  # The back edge.
        self.assertEqual(blocks["end"][-1].opcode, "ret")

    @unittest.skipUnless(shutil.which("opt"), "opt is required for the mem2reg check")
    def test_mem2reg_turns_both_arm_stores_into_a_phi(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.ll"
            self.assertEqual(self.compile(FIXTURES / "ok" / "if-else_assign-both-arms.txt", output)
                             .returncode, 0)
            promoted = subprocess.run(["opt", "-passes=mem2reg", "-S", str(output)],
                                      capture_output=True, text=True)
        self.assertEqual(promoted.returncode, 0, promoted.stderr)
        self.assertIn("%r.0 = phi i32 [ 1, %then ], [ 2, %else ]", promoted.stdout)
        self.assertNotIn("alloca", promoted.stdout)
        self.assertNotIn("store", promoted.stdout)


if __name__ == "__main__":
    unittest.main()
