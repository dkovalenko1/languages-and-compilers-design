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


I1, I8, I32, I64 = ir.IntType(1), ir.IntType(8), ir.IntType(32), ir.IntType(64)
TYPES = {"bool": I1, "i32": I32, "i64": I64}


def parse_args():
    parser = argparse.ArgumentParser(description="LLVM Compiler for practice 5")
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
        self.module = ir.Module(name="practice5")
        self.module.triple = llvm.get_default_triple()
        self.function = ir.Function(self.module, ir.FunctionType(I32, []), name="main")
        self.entry = self.function.append_basic_block("entry")
        self.builder = ir.IRBuilder(self.entry)
        self.printf = ir.Function(
            self.module, ir.FunctionType(I32, [ir.PointerType(I8)], var_arg=True),
            name="printf",
        )
        self.int_fmt = self.global_string("int_fmt", b"Program exit with result %lld\n\0")
        self.bool_fmt = self.global_string("bool_fmt", b"Program exit with result %s\n\0")
        self.true_text = self.global_string("bool_true", b"true\0")
        self.false_text = self.global_string("bool_false", b"false\0")
        self.slots = {}  # Declaration identity -> LLVM stack slot.
        self.last_alloca = None  # Slots stay in declaration order at the top of entry.

    def global_string(self, name: str, text: bytes):
        array_type = ir.ArrayType(I8, len(text))
        variable = ir.GlobalVariable(self.module, array_type, name=name)
        variable.linkage = "private"
        variable.global_constant = True
        variable.initializer = ir.Constant(array_type, bytearray(text))
        return variable

    def entry_alloca(self, type_name: str, name: str):
        """Allocate a slot at the start of the entry block, wherever the builder is.

        A slot made inside one arm of an if would not exist on the other path,
        and mem2reg only promotes allocas that stand in the entry block.
        """
        current = self.builder.block
        if self.last_alloca is None:
            self.builder.position_at_start(self.entry)
        else:
            self.builder.position_after(self.last_alloca)
        slot = self.last_alloca = self.builder.alloca(TYPES[type_name], name=name)
        self.builder.position_at_end(current)
        return slot

    def coerce(self, value, have: str, want: str):
        if have == "i32" and want == "i64":
            return self.builder.sext(value, I64, name="wide")
        return value

    def visit_program(self, node):
        for statement in node.statements:
            statement.accept(self)
        node.exit.accept(self)
        return self.module

    def visit_block(self, node):
        for statement in node.statements:
            statement.accept(self)
        if node.exit:
            node.exit.accept(self)

    def visit_if(self, node):
        condition = node.condition.accept(self)
        then_bb = self.function.append_basic_block("then")
        else_bb = self.function.append_basic_block("else") if node.else_block else None
        merge_bb = self.function.append_basic_block("merge")
        self.builder.cbranch(condition, then_bb, else_bb or merge_bb)
        for block, arm in ((then_bb, node.then_block), (else_bb, node.else_block)):
            if block is None:
                continue
            self.builder.position_at_end(block)
            arm.accept(self)
            # The current block, not the arm's first one: a nested if moved the
            # builder to its own merge. An arm that exited already has its ret.
            if not self.builder.block.is_terminated:
                self.builder.branch(merge_bb)
        self.builder.position_at_end(merge_bb)

    def visit_decl(self, node):
        value = node.init.accept(self)
        value = self.coerce(value, node.init.type, node.type_name)
        slot = self.entry_alloca(node.type_name, node.name)
        self.builder.store(value, slot)
        self.slots[id(node)] = slot

    def visit_assign(self, node):
        value = node.value.accept(self)
        value = self.coerce(value, node.value.type, node.decl.type_name)
        self.builder.store(value, self.slots[id(node.decl)])

    def visit_exit(self, node):
        value = node.value.accept(self)
        if node.value.type == "bool":
            true_pointer = self.builder.bitcast(self.true_text, ir.PointerType(I8))
            false_pointer = self.builder.bitcast(self.false_text, ir.PointerType(I8))
            text = self.builder.select(value, true_pointer, false_pointer)
            fmt = self.builder.bitcast(self.bool_fmt, ir.PointerType(I8))
            self.builder.call(self.printf, [fmt, text])
        else:
            value = self.coerce(value, node.value.type, "i64")
            fmt = self.builder.bitcast(self.int_fmt, ir.PointerType(I8))
            self.builder.call(self.printf, [fmt, value])
        self.builder.ret(ir.Constant(I32, 0))

    def visit_binop(self, node):
        left = node.left.accept(self)
        right = node.right.accept(self)
        if node.op in ("+", "-", "*"):
            operand_type = node.type
            left = self.coerce(left, node.left.type, operand_type)
            right = self.coerce(right, node.right.type, operand_type)
            return {"+": self.builder.add, "-": self.builder.sub, "*": self.builder.mul}[node.op](left, right)
        if node.left.type == "bool":
            operand_type = "bool"
        else:
            operand_type = "i64" if "i64" in (node.left.type, node.right.type) else "i32"
        left = self.coerce(left, node.left.type, operand_type)
        right = self.coerce(right, node.right.type, operand_type)
        return self.builder.icmp_signed(node.op, left, right)

    def visit_not(self, node):
        return self.builder.not_(node.operand.accept(self))

    def visit_var(self, node):
        return self.builder.load(self.slots[id(node.decl)])

    def visit_const(self, node):
        return ir.Constant(TYPES[node.type], int(node.value.lstrip("0") or "0"))

    def visit_bool(self, node):
        return ir.Constant(I1, int(node.value))


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
