"""Compile the parsed language through an AST walk and llvmlite's builder."""

import argparse
from pathlib import Path
import sys

from llvmlite import ir
import llvmlite.binding as llvm

from lexer import CompileError, lex
from parser import Parser
from semantic import SemanticChecker
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
    """Emit IR from a checked tree, with no source-language validation."""

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
        self.slots = {}  # Declaration identity -> LLVM stack slot.

    def visit_program(self, node):
        for statement in node.statements:
            statement.accept(self)
        node.exit.accept(self)
        return self.module

    def visit_decl(self, node):
        value = node.init.accept(self)
        slot = self.builder.alloca(I32, name=node.name)
        self.builder.store(value, slot)
        self.slots[id(node)] = slot

    def visit_assign(self, node):
        self.builder.store(node.value.accept(self), self.slots[id(node.decl)])

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
        return self.builder.load(self.slots[id(node.decl)])

    def visit_const(self, node):
        return ir.Constant(I32, int(node.value))


def compile_program(source: bytes):
    tree = Parser(lex(source)).parse_program()
    tree.accept(SemanticChecker())
    return tree.accept(CodeGen())


def main():
    args = parse_args()
    try:
        source = args.source.read_bytes()
        tree = Parser(lex(source)).parse_program()
        if args.ast:
            print(tree.dump())
            return 0
        tree.accept(SemanticChecker())
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
