"""Practice 7 contracts: isolated variants, fixed-point analysis and required IR."""
from pathlib import Path
import unittest

import src_path  # noqa: F401
from lexer import CompileError, lex
from parser import Parser
from semantic import SemanticChecker
from compiler import compile_program
from llvmlite import binding as llvm

ROOT = Path(__file__).resolve().parents[1]
P = '''struct P
{
    i32 mut x
    fn f := (i32 n) -> i32
    {
        x := x + n
        exit x
    }
}
'''


def checked(source):
    tree = Parser(lex(source.encode())).parse_program()
    tree.accept(SemanticChecker())
    return tree


class Practice7Tests(unittest.TestCase):
    def assert_error(self, source, fragment, line=None, column=None):
        with self.assertRaises(CompileError) as caught:
            checked(source)
        message = str(caught.exception)
        self.assertIn(fragment, message)
        self.assertRegex(message, r'line \d+:\d+:')
        if line is not None:
            self.assertIn(f'line {line}:{column}:', message)

    def test_declaration_and_call_errors(self):
        cases = [
            (P.replace('fn f', 'fn x')+'exit 0', "already", None, None),
            (P.replace('}\n}', '}\n    fn f := () -> i32\n    {\n        exit 0\n    }\n}')+'exit 0', 'declared twice', None, None),
            ('i32 n{1}\nexit n.f()', 'member function', 2, 8),
            (P+'exit P.f(1)', 'type', 10, 6),
            (P+'P mut p{1}\nexit p.f(true)', 'must be i32', 11, 10),
            (P+'P mut p{1}\nexit p.f(1, 2)', 'takes 1 argument', 11, 8),
            (P.replace('exit x', 'exit true')+'exit 0', 'must exit with i32', 7, 14),
            (P.replace('exit x', 'exit missing')+'exit 0', 'before its declaration', 7, 14),
            (P.replace('exit x', 'exit top')+'i32 top{4}\nexit 0', 'not visible', 7, 14),
            (P+'P mut p{1}\np.f(1)\nexit 0', 'a call is not a statement', 11, 1),
            (P+'P mut p{1}\nexit p.f(1).x', 'not a struct', 11, 12),
            (P+'P mut p{1}\np.f(1).x := 5\nexit 0', 'temporary', 11, 1),
        ]
        for source, message, line, column in cases:
            with self.subTest(message=message, source=source):
                self.assert_error(source, message, line, column)

    def test_reserved_names_in_every_decl_position(self):
        for name in ('read', 'print'):
            sources = [f'i32 {name}{{0}}\nexit 0',
                       f'fn {name} := () -> i32\n{{\n    exit 0\n}}\nexit 0',
                       f'fn f := (i32 {name}) -> i32\n{{\n    exit 0\n}}\nexit 0',
                       f'struct P\n{{\n    i32 {name}\n}}\nexit 0',
                       P.replace('fn f', f'fn {name}')+'exit 0',
                       P+f'P p{{0}}\nexit p.{name}()']
            for source in sources:
                with self.subTest(name=name, source=source):
                    self.assert_error(source, 'reserved')

    def test_builtin_and_string_errors(self):
        for source, message, line, column in [
            ('exit read(1)', 'takes no arguments', 1, 6),
            ('print()\nexit 0', 'exactly one argument', 1, 1),
            ('print(1, 2)\nexit 0', 'exactly one argument', 1, 1),
            ('print("unfinished', 'unterminated string', 1, 7),
            ('fn f := () -> i32\n{\n    exit print(1)\n}\nexit 0', 'no value', 3, 10),
            ('print("a" + 1)\nexit 0', "expected ')'", 1, 11),
        ]:
            with self.subTest(source=source):
                self.assert_error(source, message, line, column)

    def test_string_bytes_are_preserved_without_escapes(self):
        token = lex(b'print("100% \\n \xff")')[0][2]
        self.assertEqual(token.kind, 'string')
        self.assertEqual(token.text.encode('latin1'), b'100% \\n \xff')

    def test_mutation_fixed_point_and_nonmutating_cycles(self):
        source = '''struct P
{
    i32 mut x
    fn a := (i32 n) -> i32
    {
        exit b(n)
    }
    fn b := (i32 n) -> i32
    {
        if n == 0
        {
            exit x
        }
        exit a(n - 1)
    }
}
P p{2}
exit p.a(0)'''
        tree = checked(source)
        self.assertEqual([fn.mutating for fn in tree.structs[0].methods], [False, False])
        mutating = source.replace('        if n == 0', '        x := x + 1\n        if n == 0')
        self.assert_error(mutating, 'not mut')
        tree = checked(mutating.replace('P p{', 'P mut p{'))
        self.assertEqual([fn.mutating for fn in tree.structs[0].methods], [True, True])

    def test_member_hides_global_even_when_arguments_do_not_match(self):
        source = P.replace('        x := x + n\n', '')+'''fn f := () -> i32
{
    exit 9
}
'''
        source = source.replace('exit x', 'exit f()')+'exit 0'
        self.assert_error(source, 'takes 1 argument')

    def test_transitive_nested_mutation_is_rejected_on_const_root(self):
        source = P+'''struct W
{
    P mut p
    fn run := () -> i32
    {
        exit p.f(1)
    }
}
W w{{1}}
exit w.run()'''
        self.assert_error(source, "'w' is not mut")
        tree = checked(source.replace('W w{', 'W mut w{'))
        self.assertTrue(tree.structs[1].methods[0].mutating)

    def test_bonus_temporary_assignment_and_scalar_continuation(self):
        source = '''struct P
{
    i32 mut x
}
fn make := () -> P
{
    P p{1}
    exit p
}
make().x := 2
exit 0'''
        self.assert_error(source, 'temporary', 10, 1)
        self.assert_error('exit read().x', 'not a struct', 1, 12)

    def test_required_ir_contracts(self):
        source = (ROOT/'tests/ok/practice7_members.txt').read_bytes()
        text = str(compile_program(source))
        llvm.parse_assembly(text).verify()
        self.assertRegex(text, r'define i32 @"Point_shift"\(%"Point"\*')
        body = text.split('define i32 @"Point_shift"')[1].split('\n}')[0]
        for opcode in ('getelementptr', 'load', 'add', 'store'):
            self.assertIn(opcode, body)
        self.assertIn('call i32 @"Point_shift"(%"Point"*', text)
        text = str(compile_program((ROOT/'tests/ok/read_contexts.txt').read_bytes()))
        module = llvm.parse_assembly(text)
        module.verify()
        self.assertEqual(sum(f.name == 'printf' for f in module.functions), 1)
        self.assertEqual(sum(f.name == 'scanf' for f in module.functions), 1)
        for fn in module.functions:
            for block in list(fn.blocks)[1:]:
                self.assertNotIn('alloca', [i.opcode for i in block.instructions])
        text = str(compile_program((ROOT/'tests/ok/member_temporary.txt').read_bytes()))
        self.assertIn('extractvalue', text)
        llvm.parse_assembly(text).verify()


if __name__ == '__main__':
    unittest.main()
