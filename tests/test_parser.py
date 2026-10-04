"""Parser and AST checks independent of LLVM code generation."""

from pathlib import Path
import subprocess
import sys
import unittest

import src_path  # noqa: F401  (puts src/ on sys.path)
from lexer import CompileError, lex
from parser import Parser


ROOT = Path(__file__).resolve().parents[1]


class ParserTests(unittest.TestCase):
    def parse(self, source: bytes):
        return Parser(lex(source)).parse_program()

    def test_practice_2_tree(self):
        source = b"i32 x{0}\ni32 mut y{10}\ni32 z{2+5}\ni32 mut t{x+10}\nt:=t*z\nexit t\n"
        self.assertEqual(self.parse(source).dump(), "\n".join([
            "Program",
            "  Decl x i32 const", "    Const 0",
            "  Decl y i32 mut", "    Const 10",
            "  Decl z i32 const", "    BinOp +", "      Const 2", "      Const 5",
            "  Decl t i32 mut", "    BinOp +", "      Var x", "      Const 10",
            "  Assign t", "    BinOp *", "      Var t", "      Var z",
            "  Exit", "    Var t",
        ]))

    def test_precedence_and_left_associativity_in_dump(self):
        source = b"i32 x{2 + 3 * 4}\ni32 mut a{10 - 3 - 2}\nexit x\n"
        self.assertEqual(self.parse(source).dump(), "\n".join([
            "Program",
            "  Decl x i32 const",
            "    BinOp +",
            "      Const 2",
            "      BinOp *",
            "        Const 3",
            "        Const 4",
            "  Decl a i32 mut",
            "    BinOp -",
            "      BinOp -",
            "        Const 10",
            "        Const 3",
            "      Const 2",
            "  Exit",
            "    Var x",
        ]))

    def test_types_booleans_and_comparison_precedence(self):
        source = b"i64 x{10}\nbool b{true}\nbool c{x * 2 != x + 5}\nexit b\n"
        self.assertEqual(self.parse(source).dump(), "\n".join([
            "Program",
            "  Decl x i64 const", "    Const 10",
            "  Decl b bool const", "    Bool true",
            "  Decl c bool const",
            "    BinOp !=",
            "      BinOp *", "        Var x", "        Const 2",
            "      BinOp +", "        Var x", "        Const 5",
            "  Exit", "    Var b",
        ]))

    def test_second_comparison_is_rejected(self):
        with self.assertRaises(CompileError) as caught:
            self.parse(b"bool b{1 == 1 != 0}\nexit b")
        self.assertEqual(str(caught.exception),
                         "compilation error: line 1:15: only one comparison is allowed per expression")

    def test_parser_errors_and_columns(self):
        cases = [
            (b"+\nexit 0", "line 1:1: cannot start a statement with '+'"),
            (b"x 5\nexit 0", "line 1:3: expected ':=' after 'x'"),
            (b"i32 x\nexit 0", "line 1:5: variable 'x' needs an initialiser"),
            (b"i32 x{1} 2\nexit 0", "line 1:10: unexpected '2'"),
            (b"x := x +\nexit 0", "line 1:9: expected a constant or a variable, found end of line"),
            (b"i32 x{*}\nexit 0", "line 1:7: expected a constant or a variable, got '*'"),
            (b"exit 0\ni32 x{1}", "line 2:1: exit must be the last statement"),
            (b"i32 x{1}", "line 1:8: missing exit statement"),
        ]
        for source, expected in cases:
            with self.subTest(source=source), self.assertRaises(CompileError) as caught:
                self.parse(source)
            self.assertTrue(str(caught.exception).startswith("compilation error: " + expected))

    def test_warm_up_dump_nests_ifs_and_blocks(self):
        source = (b"i32 mut x{10}\nif true\n{\n    bool mut x{true}\n    if x\n    {\n"
                  b"        i64 mut x{20}\n        exit x\n    }\n    exit x\n}\nexit x\n")
        self.assertEqual(self.parse(source).dump(), "\n".join([
            "Program",
            "  Decl x i32 mut", "    Const 10",
            "  If",
            "    Bool true",
            "    Block",
            "      Decl x bool mut", "        Bool true",
            "      If",
            "        Var x",
            "        Block",
            "          Decl x i64 mut", "            Const 20",
            "          Exit", "            Var x",
            "      Exit", "        Var x",
            "  Exit", "    Var x",
        ]))

    def test_if_else_and_blank_lines_between_blocks(self):
        source = b"bool b{true}\nif b\n\n{\n  b := false\n}\n\nelse\n{\n  exit 1\n}\nexit b\n"
        self.assertEqual(self.parse(source).dump(), "\n".join([
            "Program",
            "  Decl b bool const", "    Bool true",
            "  If",
            "    Var b",
            "    Block", "      Assign b", "        Bool false",
            "    Block", "      Exit", "        Const 1",
            "  Exit", "    Var b",
        ]))

    def test_not_binds_to_the_next_factor(self):
        source = b"bool a{true}\nbool b{!a == ! !a}\nexit !b\n"
        self.assertEqual(self.parse(source).dump(), "\n".join([
            "Program",
            "  Decl a bool const", "    Bool true",
            "  Decl b bool const",
            "    BinOp ==",
            "      Not", "        Var a",
            "      Not", "        Not", "          Var a",
            "  Exit", "    Not", "      Var b",
        ]))

    def test_while_dump(self):
        source = b"i32 mut i{0}\nwhile i != 3\n{\n    i := i + 1\n}\nexit i\n"
        self.assertEqual(self.parse(source).dump(), "\n".join([
            "Program",
            "  Decl i i32 mut", "    Const 0",
            "  While",
            "    BinOp !=", "      Var i", "      Const 3",
            "    Block", "      Assign i", "        BinOp +", "          Var i", "          Const 1",
            "  Exit", "    Var i",
        ]))

    def test_block_errors_and_columns(self):
        cases = [
            (b"i32 mut a{1}\nbool b{true}\nif b\na := a + 1\nexit a",
             "line 4:1: expected '{' on its own line after 'if', got 'a'"),
            (b"bool b{true}\nif b {\n  exit 1\n}\nexit 0",
             "line 2:6: unexpected '{' after the statement"),
            (b"if true\n{\n}\nexit 0", "line 2:1: empty block"),
            (b"i32 a{1}\nelse\n{\n  exit 1\n}\nexit 0", "line 2:1: 'else' without an 'if'"),
            (b"if true\n{\n  exit 1\n", "line 2:1: '{' is never closed"),
            (b"if true\n{\n  i32 a{1}\nexit a\n", "line 2:1: '{' is never closed"),
            (b"if true\n{\n  exit 1\n    exit 2\n}\nexit 0",
             "line 4:5: statement after 'exit' in the same block"),
            (b"i32 x{5\nexit x", "line 1:8: expected '}', found end of line"),
            (b"if true\n{\n  exit 1\n}\n}\nexit 0", "line 5:1: '}' without a matching '{'"),
            (b"if true\n{\n  exit 1\n} else\n{\n  exit 2\n}\nexit 0",
             "line 4:3: unexpected 'else' after the statement"),
            (b"if true\n{\n  exit 1\n}\nelse\nexit 0",
             "line 6:1: expected '{' on its own line after 'else', got 'exit'"),
            (b"if true", "line 1:8: expected '{' on its own line after 'if', found end of file"),
            (b"bool b{true}\n!b\nexit b", "line 2:1: cannot start a statement with '!'"),
            (b"bool b{!}\nexit b", "line 1:9: expected a constant or a variable, got '}'"),
            (b"while true {\n  exit 1\n}\nexit 0", "line 1:12: unexpected '{' after the statement"),
            (b"while true\n{\n}\nexit 0", "line 2:1: empty block"),
            (b"while true\nexit 0", "line 2:1: expected '{' on its own line after 'while', got 'exit'"),
        ]
        for source, expected in cases:
            with self.subTest(source=source), self.assertRaises(CompileError) as caught:
                self.parse(source)
            self.assertEqual(str(caught.exception), "compilation error: " + expected)

    def test_ast_cli_does_not_write_ir(self):
        source = ROOT / "tests" / "valid" / "worked_example.txt"
        run = subprocess.run(
            [sys.executable, "-B", str(ROOT / "src" / "compiler.py"), "--ast", str(source)],
            capture_output=True, text=True,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(run.stdout.startswith("Program\n  Decl "))
        self.assertEqual(run.stderr, "")


if __name__ == "__main__":
    unittest.main()
