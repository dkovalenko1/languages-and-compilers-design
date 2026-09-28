"""Type and name checks run on the AST without constructing LLVM IR."""

import unittest

from lexer import CompileError, lex
from parser import Parser
from semantic import SemanticChecker


def check(source: bytes):
    tree = Parser(lex(source)).parse_program()
    tree.accept(SemanticChecker())
    return tree


class SemanticTests(unittest.TestCase):
    def test_rule_errors_with_source_positions(self):
        cases = [
            (b"bool b{true}\ni32 x{b + 1}\nexit x",
             "line 2:9: cannot apply '+' to bool"),
            (b"bool b{true}\nbool c{b == 1}\nexit c",
             "line 2:10: cannot compare bool with i32"),
            (b"i64 a{3000000000}\ni32 c{a}\nexit c",
             "line 2:5: cannot initialise 'c' of type i32 with a value of type i64"),
            (b"i64 a{3000000000}\ni32 mut x{1}\nx := a\nexit x",
             "line 3:1: cannot assign to 'x' of type i32 with a value of type i64"),
            (b"i32 x{3000000000}\nexit x",
             "line 1:7: constant 3000000000 does not fit in i32"),
            (b"bool b{1}\nexit b",
             "line 1:6: cannot initialise 'b' of type bool with a value of type i32"),
            (b"i64 x{99999999999999999999}\nexit x",
             "line 1:7: constant 99999999999999999999 does not fit in i64"),
            (b"i32 x{y}\nexit x",
             "line 1:7: variable 'y' is used before its declaration"),
            (b"i32 x{1}\ni32 x{2}\nexit x",
             "line 2:5: variable 'x' is declared twice"),
            (b"i32 x{1}\nx := 2\nexit x",
             "line 2:1: cannot assign to 'x': it is not mut"),
        ]
        for source, expected in cases:
            with self.subTest(source=source), self.assertRaises(CompileError) as caught:
                check(source)
            self.assertEqual(str(caught.exception), "compilation error: " + expected)

    def test_corrected_programs_are_accepted(self):
        sources = [
            b"i32 b{1}\ni32 x{b + 1}\nexit x",
            b"bool b{true}\nbool c{b == false}\nexit c",
            b"i64 a{3000000000}\ni64 c{a}\nexit c",
            b"i64 a{3000000000}\ni64 mut x{1}\nx := a\nexit x",
            b"i64 x{3000000000}\nexit x",
            b"bool b{true}\nexit b",
            b"i64 x{9223372036854775807}\nexit x",
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertIsNotNone(check(source))

    def test_types_and_resolved_declarations_are_recorded(self):
        tree = check(b"i32 a{10}\ni64 mut b{a}\nb := a + 3000000000\nbool c{b != a}\nexit c")
        a, b, assignment, c = tree.statements
        self.assertEqual(a.init.type, "i32")
        self.assertEqual(b.init.type, "i32")
        self.assertIs(b.init.decl, a)
        self.assertIs(assignment.decl, b)
        self.assertEqual(assignment.value.type, "i64")
        self.assertEqual(assignment.value.right.type, "i64")
        self.assertEqual(c.init.type, "bool")
        self.assertIs(tree.exit.value.decl, c)


if __name__ == "__main__":
    unittest.main()
