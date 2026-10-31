"""Compile the parsed language through an AST walk and llvmlite's builder."""

import argparse
from pathlib import Path
import sys

from llvmlite import ir
import llvmlite.binding as llvm

from ast_nodes import FieldNode, InitNode, FieldDeclNode, VarNode, ThisNode, StringNode, CallNode
from lexer import CompileError, lex
from parser import Parser
from semantic import SemanticChecker
from terminal_output import print_error


I1, I8, I32, I64 = ir.IntType(1), ir.IntType(8), ir.IntType(32), ir.IntType(64)
TYPES = {"bool": I1, "i32": I32, "i64": I64}
ZERO = ir.Constant(I32, 0)
FN_PREFIX = "fn."  # '.' cannot appear in a source name, so no prefixed name meets the runtime's.


def parse_args():
    parser = argparse.ArgumentParser(description="LLVM Compiler for practice 8")
    parser.add_argument("--ast", action="store_true", help="Print the syntax tree without writing IR")
    parser.add_argument("--ast-checked", action="store_true",
                        help="Print the tree after the semantic pass without writing IR")
    parser.add_argument("source", type=Path, help="Path to the source program")
    parser.add_argument("output", type=Path, nargs="?", help="Path to the output LLVM IR file")
    args = parser.parse_args()
    if args.ast or args.ast_checked:
        if args.ast and args.ast_checked:
            parser.error("--ast and --ast-checked cannot be combined")
        if args.output is not None:
            parser.error("--ast and --ast-checked take only a source path")
        return args
    if args.output is None:
        parser.error("the output .ll path is required unless --ast or --ast-checked is used")
    if args.output.suffix != ".ll":
        parser.error("Output file must have a .ll extension")
    if args.source.resolve() == args.output.resolve():
        parser.error("Source and output must be different files")
    return args


class CodeGen:
    """Emit IR from a checked tree, with no source-language validation."""

    def __init__(self):
        self.module = ir.Module(name="practice7", context=ir.Context())
        self.module.triple = llvm.get_default_triple()
        self.types = dict(TYPES)  # Source type name -> LLVM type; structs are added in order.
        self.field_types = {}  # Struct name -> its fields' source type names, by index.
        self.field_names = {}
        self.field_indices = {}
        self.strings = {}
        self.this = None
        self.scanf = None
        self.functions = {}  # Id of an FnNode -> its ir.Function.
        self.function = self.entry = self.builder = self.result_type = None
        self.printf = ir.Function(
            self.module, ir.FunctionType(I32, [ir.PointerType(I8)], var_arg=True),
            name="printf",
        )
        self.int_fmt = self.global_string("int_fmt", b"Program exit with result %lld\n\0")
        self.bool_fmt = self.global_string("bool_fmt", b"Program exit with result %s\n\0")
        self.true_text = self.global_string("bool_true", b"true\0")
        self.false_text = self.global_string("bool_false", b"false\0")
        self.slots = {}  # Declaration or parameter identity -> LLVM stack slot.
        self.last_alloca = None  # Slots stay in declaration order at the top of entry.

    def begin_function(self, function: ir.Function, result_type: str | None):
        """Point the builder at a new function's entry block; result_type None is main."""
        self.function, self.result_type = function, result_type
        self.entry = function.append_basic_block("entry")
        self.builder = ir.IRBuilder(self.entry)
        self.last_alloca = None
        self.this = None

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
        slot = self.last_alloca = self.builder.alloca(self.types[type_name], name=name)
        self.builder.position_at_end(current)
        return slot

    def coerce(self, value, have: str, want: str):
        if have == "i32" and want == "i64":
            return self.builder.sext(value, I64, name="wide")
        return value

    def visit_program(self, node):
        for struct in node.structs:
            struct.accept(self)
        # Every function exists in the module before any body is built, so
        # a call may refer to a function defined below it.
        functions = [fn for struct in node.structs for fn in struct.methods] + node.functions
        for fn in functions:
            parameters = [self.types[param.type_name] for param in fn.params]
            if fn.owner:
                parameters.insert(0, self.types[fn.owner].as_pointer())
            signature = ir.FunctionType(self.types[fn.result_type], parameters)
            name = fn.owner + "_" + fn.name if fn.owner else FN_PREFIX + fn.name
            function = ir.Function(self.module, signature, name=self.module.get_unique_name(name))
            arguments = list(function.args)
            if fn.owner:
                arguments.pop(0).name = "this"
            for argument, param in zip(arguments, fn.params):
                argument.name = param.name
            self.functions[id(fn)] = function
        for fn in functions:
            fn.accept(self)
        self.begin_function(ir.Function(self.module, ir.FunctionType(I32, []), name="main"), None)
        for statement in node.statements:
            statement.accept(self)
        node.exit.accept(self)
        return self.module

    def visit_struct(self, node):
        struct_type = self.module.context.get_identified_type(node.name)
        struct_type.set_body(*(self.types[field.type_name] for field in node.fields))
        self.types[node.name] = struct_type
        self.field_types[node.name] = [field.type_name for field in node.fields]
        self.field_names[node.name] = [field.name for field in node.fields]
        for index, field in enumerate(node.fields):
            self.field_indices[id(field)] = index

    def visit_fn(self, node):
        function = self.functions[id(node)]
        self.begin_function(function, node.result_type)
        arguments = list(function.args)
        if node.owner:
            self.this = arguments.pop(0)
        for argument, param in zip(arguments, node.params):
            slot = self.entry_alloca(param.type_name, param.name + ".slot")
            self.builder.store(argument, slot)
            self.slots[id(param)] = slot
        node.body.accept(self)  # The body ends with exit, so its last block has a ret.

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

    def visit_while(self, node):
        cond_bb = self.function.append_basic_block("cond")
        body_bb = self.function.append_basic_block("body")
        end_bb = self.function.append_basic_block("end")
        self.builder.branch(cond_bb)
        self.builder.position_at_end(cond_bb)  # The condition is re-read on every pass.
        self.builder.cbranch(node.condition.accept(self), body_bb, end_bb)
        self.builder.position_at_end(body_bb)
        node.body.accept(self)
        if not self.builder.block.is_terminated:
            self.builder.branch(cond_bb)  # The back edge.
        self.builder.position_at_end(end_bb)

    def visit_decl(self, node):
        slot = self.entry_alloca(node.type_name, node.name)
        init = node.init
        if node.type_name in TYPES or init.copy:
            value = init.items[0]
            self.builder.store(self.coerce(value.accept(self), value.type, node.type_name), slot)
        else:
            # An object is filled field by field through a gep at the field's index.
            fields = self.field_types[node.type_name]
            for index, item in enumerate(init.items):
                address = self.builder.gep(slot, [ZERO, ir.Constant(I32, index)], inbounds=True)
                self.builder.store(self.init_value(item, fields[index]), address)
        self.slots[id(node)] = slot

    def init_value(self, item, type_name: str):
        """The value of one field: an expression, or a nested {} built with insertvalue."""
        if not isinstance(item, InitNode):
            return self.coerce(item.accept(self), item.type, type_name)
        if item.copy:  # An inner {} follows the outer rules: {p} copies p.
            return item.items[0].accept(self)
        value = ir.Constant(self.types[type_name], ir.Undefined)
        for index, (inner, field_type) in enumerate(zip(item.items, self.field_types[type_name])):
            value = self.builder.insert_value(value, self.init_value(inner, field_type), index)
        return value

    def address(self, node):
        """The slot of a variable, or a gep through the indices of a field chain."""
        if isinstance(node, FieldNode):
            return self.builder.gep(self.address(node.base), [ZERO, ir.Constant(I32, node.index)],
                                    inbounds=True)
        if isinstance(node, ThisNode):
            return self.this
        if isinstance(node, VarNode):
            if isinstance(node.decl, FieldDeclNode):
                return self.builder.gep(self.this, [ZERO, ir.Constant(I32, self.field_indices[id(node.decl)])],
                                        inbounds=True)
            return self.slots[id(node.decl)]
        value = node.accept(self)
        slot = self.entry_alloca(node.type, "temporary")
        self.builder.store(value, slot)
        return slot

    def visit_assign(self, node):
        value = node.value.accept(self)
        value = self.coerce(value, node.value.type, node.target.type)
        self.builder.store(value, self.address(node.target))

    def visit_exit(self, node):
        value = node.value.accept(self)
        if self.result_type is not None:  # In a function, exit returns its result.
            self.builder.ret(self.coerce(value, node.value.type, self.result_type))
            return
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
        return self.builder.load(self.address(node))

    def visit_field(self, node):
        base = node.base
        while isinstance(base, FieldNode):
            base = base.base
        if isinstance(base, CallNode):
            return self.builder.extract_value(node.base.accept(self), node.index)
        return self.builder.load(self.address(node))

    def visit_call(self, node):
        # Evaluate the receiver before arguments, once, and retain its address.
        receiver = [self.address(node.receiver)] if node.function.owner else []
        args = [self.coerce(arg.accept(self), arg.type, param.type_name)
                for arg, param in zip(node.args, node.function.params)]
        return self.builder.call(self.functions[id(node.function)], receiver + args, name="call.ret")

    def visit_member_call(self, node):
        return self.visit_call(node)

    def visit_this(self, node):
        return self.builder.load(self.this)

    def text_pointer(self, text: bytes):
        if text not in self.strings:
            self.strings[text] = self.global_string("text." + str(len(self.strings)), text + b"\0")
        return self.builder.bitcast(self.strings[text], I8.as_pointer())

    def emit_text(self, text: bytes):
        # Literals allow arbitrary bytes, including NUL, which terminates %s.
        # Emit those bytes with %c and keep the remaining text behind %s.
        for index, part in enumerate(text.split(b"\0")):
            if index:
                self.builder.call(self.printf, [self.text_pointer(b"%c"), ZERO])
            self.builder.call(self.printf, [self.text_pointer(b"%s"), self.text_pointer(part)])

    def print_value(self, value, type_name):
        if type_name == "bool":
            value = self.builder.select(value,
                                        self.builder.bitcast(self.true_text, I8.as_pointer()),
                                        self.builder.bitcast(self.false_text, I8.as_pointer()))
            fmt = b"%s"
        else:
            fmt = b"%d" if type_name == "i32" else b"%lld"
        self.builder.call(self.printf, [self.text_pointer(fmt), value])

    def print_struct(self, address, type_name):
        self.emit_text(type_name.encode("ascii") + b"{")
        for index, (name, field_type) in enumerate(zip(self.field_names[type_name], self.field_types[type_name])):
            self.emit_text(((", " if index else "") + name + ": ").encode("ascii"))
            field = self.builder.gep(address, [ZERO, ir.Constant(I32, index)], inbounds=True)
            if field_type in TYPES:
                self.print_value(self.builder.load(field), field_type)
            else:
                self.print_struct(field, field_type)
        self.emit_text(b"}")

    def visit_print(self, node):
        value = node.value
        if isinstance(value, StringNode):
            self.emit_text(value.value.encode("latin1"))
        elif value.type not in TYPES:
            self.print_struct(self.address(value), value.type)
        else:
            self.print_value(value.accept(self), value.type)
        self.emit_text(b"\n")

    def visit_read(self, node):
        if self.scanf is None:
            self.scanf = ir.Function(self.module, ir.FunctionType(I32, [I8.as_pointer()], var_arg=True),
                                     name="scanf")
        slot = self.entry_alloca("i32", "read.slot")
        self.builder.call(self.scanf, [self.text_pointer(b"%d"), slot])
        return self.builder.load(slot)

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
        if args.ast_checked:
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
