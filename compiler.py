import argparse
from pathlib import Path
import sys
from typing import NoReturn

from llvmlite import ir
import llvmlite.binding as llvm

from lexer import CompileError, Token, lex
from parser import Parser
from terminal_output import print_error

I32, I8 = ir.IntType(32), ir.IntType(8)


def fail(token: Token, message: str) -> NoReturn:
    raise CompileError(token.line, token.column, message)


class Statement:
    """A cursor over one line of tokens; never reads source text."""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.index = 0

    def peek(self) -> Token | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self, kind: str, message: str) -> Token:
        token = self.peek()
        if token is None or token.kind != kind:
            fail(token or self.tokens[-1], message)
        self.index += 1
        return token

    def finish(self):
        token = self.peek()
        if token is not None:
            fail(token, "extra tokens on a line")


def parse_args():
    parser = argparse.ArgumentParser(description="LLVM Compiler for practice 2")
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


def compile_program(source: bytes):
    lines = lex(source)
    module = ir.Module(name="practice2")
    module.triple = llvm.get_default_triple()
    main = ir.Function(module, ir.FunctionType(I32, []), name="main")
    builder = ir.IRBuilder(main.append_basic_block("entry"))
    printf = ir.Function(
        module, ir.FunctionType(I32, [ir.PointerType(I8)], var_arg=True),
        name="printf",
    )
    text = b"Program exit with result %d\n\0"
    array_type = ir.ArrayType(I8, len(text))
    fmt = ir.GlobalVariable(module, array_type, name="fmt")
    fmt.linkage = "private"
    fmt.global_constant = True
    fmt.initializer = ir.Constant(array_type, bytearray(text))  # pyright: ignore[reportAttributeAccessIssue]

    symbols = {}  # Source name -> (LLVM stack slot, mutable).
    exited = False

    def require_declared(token):
        if token.text not in symbols:
            fail(token, f"variable '{token.text}' is used before its declaration")
        return symbols[token.text]

    def operand_value(statement: Statement):
        token = statement.peek()
        if token is None or token.kind not in ("number", "ident"):
            fail(token or statement.tokens[-1], "expected a constant or variable")
        statement.index += 1
        if token.kind == "number":
            # Compare strings before int() to handle arbitrarily long literals.
            digits = token.text.lstrip("0") or "0"
            limit = "2147483647"
            if len(digits) > len(limit) or (len(digits) == len(limit) and digits > limit):
                fail(token, "integer literal outside signed 32-bit range")
            return ir.Constant(I32, int(digits))
        slot, _ = require_declared(token)
        return builder.load(slot)

    def expression(statement):
        value = operand_value(statement)
        operator = statement.peek()
        operations = {"plus": builder.add, "minus": builder.sub, "star": builder.mul}
        if operator is not None and operator.kind in operations:
            statement.index += 1
            value = operations[operator.kind](value, operand_value(statement))
        return value

    for tokens in lines:
        if not tokens:
            continue
        statement = Statement(tokens)
        first = tokens[0]
        if exited:
            fail(first, "exit must be the last statement")

        if first.kind == "type":
            statement.index += 1
            specifier = statement.peek()
            mutable = specifier is not None and specifier.kind == "specifier"
            if mutable:
                statement.index += 1
            name = statement.take("ident", "expected a variable name")
            if name.text in symbols:
                fail(name, f"variable '{name.text}' is declared twice")
            statement.take("lbrace", f"variable '{name.text}' needs an initialiser in {{}}")
            value = expression(statement)
            statement.take("rbrace", "expected '}' after the initialiser")
            statement.finish()
            slot = builder.alloca(I32, name=name.text)
            builder.store(value, slot)
            symbols[name.text] = (slot, mutable)
            continue

        if first.kind == "ident":
            statement.index += 1
            statement.take("assign", "expected ':=' after the variable name")
            slot, mutable = require_declared(first)
            if not mutable:
                fail(first, f"cannot assign to '{first.text}': it is not mut")
            value = expression(statement)
            statement.finish()
            builder.store(value, slot)
            continue

        if first.kind == "exit":
            statement.index += 1
            value = operand_value(statement)
            statement.finish()
            pointer = builder.bitcast(fmt, ir.PointerType(I8))
            builder.call(printf, [pointer, value])
            builder.ret(ir.Constant(I32, 0))
            exited = True
            continue

        fail(first, "invalid statement")

    if not exited:
        last = next((tokens[-1] for tokens in reversed(lines) if tokens), None)
        if last is not None:
            fail(last, "missing exit statement")
        raise CompileError(1, 1, "missing exit statement")
    return module


def main():
    args = parse_args()
    try:
        source = args.source.read_bytes()
        if args.ast:
            print(Parser(lex(source)).parse_program().dump())
            return 0
        module = compile_program(source)
        # Open the output only after every source line has passed validation.
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
