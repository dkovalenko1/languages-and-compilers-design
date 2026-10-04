import unittest

from lexer import CompileError, lex


class LexerTests(unittest.TestCase):
    def test_worked_example(self):
        lines = lex(b"   i32 mut x{ 10 }\n var t")
        actual = [[(t.kind, t.text, t.line, t.column) for t in row] for row in lines]
        self.assertEqual(actual, [
            [("type", "i32", 1, 4), ("specifier", "mut", 1, 8),
            ("ident", "x", 1, 12), ("lbrace", "{", 1, 13),
            ("number", "10", 1, 15), ("rbrace", "}", 1, 18)],
            [("ident", "var", 2, 2), ("ident", "t", 2, 6)],
        ])

    def test_adjacent_tokens_and_keyword_boundaries(self):
        tokens = lex(b"_x2:=10+mutant-i32x*exit2")[0]
        self.assertEqual([(t.kind, t.text) for t in tokens], [
            ("ident", "_x2"), ("assign", ":="), ("number", "10"),
            ("plus", "+"), ("ident", "mutant"), ("minus", "-"),
            ("ident", "i32x"), ("star", "*"), ("ident", "exit2"),
        ])

    def test_blank_lines_tabs_and_eof(self):
        self.assertEqual(lex(b""), [])
        self.assertEqual(lex(b" \t"), [])
        for ending in (b"", b"\n"):
            with self.subTest(ending=ending):
                lines = lex(b"\n\t exit 42" + ending)
                self.assertEqual(lines[0], [])
                self.assertEqual([(t.text, t.line, t.column) for t in lines[1]],
                                [("exit", 2, 3), ("42", 2, 8)])

    def test_lexical_errors_and_positions(self):
        cases = [
            (b"\n       $", "line 2:8: unexpected byte '$'"),
            (b"i32 x{10\n", "line 1:6: '{' is not closed"),
            (b"i32 x{10", "line 1:6: '{' is not closed"),
            (b"  10x", "line 1:3: a number cannot contain"),
            (b"10_", "line 1:1: a number cannot contain"),
            (b"x: 1", "line 1:2: ':' must be followed by '='"),
            (b"x:", "line 1:2: ':' must be followed by '='"),
            (b"=", "line 1:1: expected '=='"),
            (b"!", "line 1:1: expected '!='"),
            (b"a = 1", "line 1:3: expected '=='"),
            (b"!b", "line 1:1: expected '!='"),
            (b"\xff", "line 1:1: unexpected byte 0xff"),
            (b"\r\n", "line 1:1: unexpected byte 0x0d"),
        ]
        for source, message in cases:
            with self.subTest(source=source):
                with self.assertRaises(CompileError) as caught:
                    lex(source)
                self.assertTrue(str(caught.exception).startswith("compilation error: " + message))

    def test_statement_validation_is_left_to_task_two(self):
        self.assertEqual([t.text for t in lex(b"mut exit }")[0]], ["mut", "exit", "}"])

    def test_new_type_boolean_and_comparison_tokens(self):
        tokens = lex(b"i64 n{10} bool b{true} bool c{false} n==10 b!=c")[0]
        self.assertEqual([(t.kind, t.text) for t in tokens], [
            ("type", "i64"), ("ident", "n"), ("lbrace", "{"),
            ("number", "10"), ("rbrace", "}"),
            ("type", "bool"), ("ident", "b"), ("lbrace", "{"),
            ("boolean", "true"), ("rbrace", "}"),
            ("type", "bool"), ("ident", "c"), ("lbrace", "{"),
            ("boolean", "false"), ("rbrace", "}"),
            ("ident", "n"), ("eq", "=="), ("number", "10"),
            ("ident", "b"), ("ne", "!="), ("ident", "c"),
        ])


if __name__ == "__main__":
    unittest.main()
