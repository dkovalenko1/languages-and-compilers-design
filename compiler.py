import argparse
from pathlib import Path
import re
import sys

from llvmlite import ir
import llvmlite.binding as llvm

NAME = r"[A-Za-z_][A-Za-z0-9_]*"
INTEGER = r"-?[0-9]+"
OPERAND = rf"(?:{INTEGER}|{NAME})"
DECLARATION = re.compile(rf"int\s+({NAME})")
ASSIGNMENT = re.compile(
    rf"({NAME})\s*:=\s*({OPERAND})(?:\s*([+*-])\s*({OPERAND}))?"
)
EXIT = re.compile(rf"exit\s+({NAME})")
RESERVED = {"int", "exit"}
I32, I8 = ir.IntType(32), ir.IntType(8)


class CompilationError(Exception):
    def __init__(self, line_number, message):
        super().__init__(f"compilation error: line {line_number}: {message}")


def parse_args():
    parser = argparse.ArgumentParser(description="LLVM Compiler for practice 1")
    parser.add_argument("source", type=Path, help="Path to the source program")
    parser.add_argument("output", type=Path, help="Path to the output LLVM IR file")
    args = parser.parse_args()
    if args.output.suffix != ".ll":
        parser.error("Output file must have a .ll extension")
    if args.source.resolve() == args.output.resolve():
        parser.error("Source and output must be different files")
    return args


def compile_program(source):
    module = ir.Module(name="practice1")
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

    symbols = {}  # Source name -> LLVM stack slot.
    initialized = set()
    exited = False
    lines = source.splitlines()

    def require_declared(name, line_number):
        if name in RESERVED:
            raise CompilationError(line_number, f"reserved name '{name}'")
        if name not in symbols:
            raise CompilationError(line_number, f"undeclared variable '{name}'")

    def operand_value(token, line_number):
        if re.fullmatch(INTEGER, token):
            # Compare strings before int() to handle arbitrarily long literals.
            digits = token.lstrip("-").lstrip("0") or "0"
            limit = "2147483648" if token.startswith("-") else "2147483647"
            if len(digits) > len(limit) or (len(digits) == len(limit) and digits > limit):
                raise CompilationError(line_number, "integer literal outside signed 32-bit range")
            value = int(digits) * (-1 if token.startswith("-") else 1)
            return ir.Constant(I32, value)
        require_declared(token, line_number)
        if token not in initialized:
            raise CompilationError(line_number, f"variable '{token}' used before assignment")
        return builder.load(symbols[token])

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if exited:
            raise CompilationError(line_number, "exit must be the last line")

        declaration = DECLARATION.fullmatch(line)
        if declaration:
            name = declaration.group(1)
            if name in RESERVED:
                raise CompilationError(line_number, f"reserved name '{name}'")
            if name in symbols:
                raise CompilationError(line_number, f"redeclared variable '{name}'")
            symbols[name] = builder.alloca(I32, name=name)
            continue

        assignment = ASSIGNMENT.fullmatch(line)
        if assignment:
            target, left, operator, right = assignment.groups()
            require_declared(target, line_number)
            value = operand_value(left, line_number)
            if operator is not None:
                rhs = operand_value(right, line_number)
                operations = {"+": builder.add, "-": builder.sub, "*": builder.mul}
                value = operations[operator](value, rhs)
            builder.store(value, symbols[target])
            initialized.add(target)
            continue

        exit_statement = EXIT.fullmatch(line)
        if exit_statement:
            value = operand_value(exit_statement.group(1), line_number)
            pointer = builder.bitcast(fmt, ir.PointerType(I8))
            builder.call(printf, [pointer, value])
            builder.ret(ir.Constant(I32, 0))
            exited = True
            continue

        raise CompilationError(line_number, "invalid statement")

    if not exited:
        raise CompilationError(len(lines) + 1, "missing exit statement")
    return module


def main():
    args = parse_args()
    try:
        source = args.source.read_text(encoding="utf-8")
        module = compile_program(source)
        # Open the output only after every source line has passed validation.
        args.output.write_text(str(module), encoding="utf-8")
    except CompilationError as error:
        print(error, file=sys.stderr)
        return 1
    except (OSError, UnicodeError) as error:
        print(f"compiler error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
