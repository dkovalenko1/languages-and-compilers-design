"""Compile the parsed language through an AST walk and llvmlite's builder."""

import argparse
from pathlib import Path
import sys

from llvmlite import ir
import llvmlite.binding as llvm

from lexer import CompileError, lex
from parser import Parser
from terminal_output import print_error


I32, I8 = ir.IntType(32), ir.IntType(8)


def parse_args():
    parser = argparse.ArgumentParser(description="LLVM Compiler for practice 3")
    parser.add_argument("--ast", action="store_true", help="Print the syntax tree without writing IR")
    parser.add_argument("source", type=Path, help="Path to the source program")
    parser.add_argument("output", type=Path, nargs="?", help="Path to the output LLVM IR file")
    args = parser.parse_args()
    if args.ast:
        if args.output is not None:
            parser.error("--ast takes only a source path")
        return args
    if args.output is None:
        parser.error("the output .ll path is required unless --ast is used")
    if args.output.suffix != ".ll":
        parser.error("Output file must have a .ll extension")
    if args.source.resolve() == args.output.resolve():
        parser.error("Source and output must be different files")
    return args


class CodeGen:
    """Emit IR from a complete tree; source checks use AST positions."""

    def __init__(self):
        self.module = ir.Module(name="practice3")
        self.module.triple = llvm.get_default_triple()
        main = ir.Function(self.module, ir.FunctionType(I32, []), name="main")
        self.builder = ir.IRBuilder(main.append_basic_block("entry"))
        self.printf = ir.Function(
            self.module, ir.FunctionType(I32, [ir.PointerType(I8)], var_arg=True),
            name="printf",
        )
        text = b"Program exit with result %d\n\0"
        array_type = ir.ArrayType(I8, len(text))
        self.fmt = ir.GlobalVariable(self.module, array_type, name="fmt")
        self.fmt.linkage = "private"
        self.fmt.global_constant = True
        self.fmt.initializer = ir.Constant(array_type, bytearray(text))
        self.symbols = {}  # Source name -> (LLVM stack slot, mutable).

    def fail(self, node, message):
        raise CompileError(node.line, node.column, message)

    def require_declared(self, node):
        if node.name not in self.symbols:
            self.fail(node, f"variable '{node.name}' is used before its declaration")
        return self.symbols[node.name]

    def visit_program(self, node):
        for statement in node.statements:
            statement.accept(self)
        node.exit.accept(self)
        return self.module

    def visit_decl(self, node):
        if node.name in self.symbols:
            self.fail(node, f"variable '{node.name}' is declared twice")
        # The initialiser runs before the name enters scope, including x{x}.
        value = node.init.accept(self)
        slot = self.builder.alloca(I32, name=node.name)
        self.builder.store(value, slot)
        self.symbols[node.name] = (slot, node.mutable)

    def visit_assign(self, node):
        slot, mutable = self.require_declared(node)
        if not mutable:
            self.fail(node, f"cannot assign to '{node.name}': it is not mut")
        self.builder.store(node.value.accept(self), slot)

    def visit_exit(self, node):
        value = node.value.accept(self)
        pointer = self.builder.bitcast(self.fmt, ir.PointerType(I8))
        self.builder.call(self.printf, [pointer, value])
        self.builder.ret(ir.Constant(I32, 0))

    def visit_binop(self, node):
        left = node.left.accept(self)
        right = node.right.accept(self)
        return {"+": self.builder.add, "-": self.builder.sub, "*": self.builder.mul}[node.op](left, right)

    def visit_var(self, node):
        slot, _ = self.require_declared(node)
        return self.builder.load(slot)

    def visit_const(self, node):
        digits = node.value.lstrip("0") or "0"
        limit = "2147483647"
        if len(digits) > len(limit) or (len(digits) == len(limit) and digits > limit):
            self.fail(node, "integer literal outside signed 32-bit range")
        return ir.Constant(I32, int(digits))


def compile_program(source: bytes):
    tree = Parser(lex(source)).parse_program()
    return tree.accept(CodeGen())


def main():
    args = parse_args()
    try:
        source = args.source.read_bytes()
        tree = Parser(lex(source)).parse_program()
        if args.ast:
            print(tree.dump())
            return 0
        module = tree.accept(CodeGen())
        # Open the output only after the entire tree passed validation.
        args.output.write_text(str(module), encoding="utf-8")
    except CompileError as error:
        print_error(error)
        return 1
    except (OSError, UnicodeError) as error:
        print_error(f"compiler error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
