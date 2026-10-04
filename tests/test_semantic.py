"""Type and name checks run on the AST without constructing LLVM IR."""

import unittest

import src_path  # noqa: F401  (puts src/ on sys.path)
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

    def test_scope_and_bool_errors_with_source_positions(self):
        cases = [
            (b"i32 a{1}\nif a\n{\n    exit 1\n}\nexit 0",
             "line 2:1: the condition of 'if' must be bool, got i32"),
            (b"i32 a{1}\nbool b{!a}\nexit b",
             "line 2:8: cannot apply '!' to i32"),
            (b"if true\n{\n    i32 inner{1}\n}\nexit inner",
             "line 5:6: variable 'inner' is used before its declaration"),
            (b"if true\n{\n    i32 a{1}\n    i32 a{2}\n    exit a\n}\nexit 0",
             "line 4:9: variable 'a' is already declared in this block"),
            (b"i32 mut x{1}\nif true\n{\n    bool mut x{true}\n    x := 5\n}\nexit x",
             "line 5:5: cannot assign to 'x' of type bool with a value of type i32"),
            (b"i64 n{1}\nif n == 1\n{\n    i32 x{n}\n    exit x\n}\nexit 0",
             "line 4:9: cannot initialise 'x' of type i32 with a value of type i64"),
            (b"bool b{true}\nif b\n{\n    exit !1\n}\nexit 0",
             "line 4:10: cannot apply '!' to i32"),
            (b"if true\n{\n    exit 1\n}\nelse\n{\n    i32 e{1}\n}\nexit e",
             "line 9:6: variable 'e' is used before its declaration"),
            (b"i32 x{1}\nif true\n{\n    x := 2\n}\nexit x",
             "line 4:5: cannot assign to 'x': it is not mut"),
        ]
        for source, expected in cases:
            with self.subTest(source=source), self.assertRaises(CompileError) as caught:
                check(source)
            self.assertEqual(str(caught.exception), "compilation error: " + expected)

    def test_shadowing_resolves_each_use_to_its_own_declaration(self):
        tree = check(b"i32 mut x{10}\nif true\n{\n    bool mut x{true}\n    if x\n    {\n"
                     b"        i64 mut x{20}\n        exit x\n    }\n    exit x\n}\nexit x\n")
        outer = tree.statements[0]
        middle_block = tree.statements[1].then_block
        middle, inner_if = middle_block.statements
        inner_block = inner_if.then_block
        inner = inner_block.statements[0]
        self.assertEqual([outer.type_name, middle.type_name, inner.type_name], ["i32", "bool", "i64"])
        self.assertIs(inner_if.condition.decl, middle)
        self.assertIs(inner_block.exit.value.decl, inner)
        self.assertEqual(inner_block.exit.value.type, "i64")
        self.assertIs(middle_block.exit.value.decl, middle)
        self.assertIs(tree.exit.value.decl, outer)

    def test_scopes_reopen_and_outer_names_stay_visible(self):
        tree = check(b"i32 mut a{1}\nbool c{true}\nif !c\n{\n    i32 t{2}\n    a := t\n}\nelse\n{\n"
                     b"    i64 t{3}\n    a := a + 1\n}\ni32 t{4}\nexit t\n")
        if_node = tree.statements[2]
        self.assertEqual(if_node.condition.type, "bool")
        self.assertIs(if_node.then_block.statements[1].decl, tree.statements[0])
        self.assertIs(tree.exit.value.decl, tree.statements[3])


if __name__ == "__main__":
    unittest.main()
