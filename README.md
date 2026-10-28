# Languages and Compilers Design

A small compiler built with a hand-written byte lexer, a recursive-descent
parser, a separate semantic checker, and LLVM code generation through
`llvmlite.ir`. It compiles a typed language with structs, functions, member
functions, control flow, and standard input/output. Diagnostics include
source line and column numbers.

## Getting started

Install Python, LLVM (`lli`, `llc`, and `opt`), and Clang. The project is
verified on Ubuntu 24.04. Create and activate a Python environment, then
install the pinned dependency:

```sh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Compile a program to LLVM IR and run it:

```sh
python3 src/compiler.py tests/ok/practice7_members.txt output.ll
lli output.ll
```

This example prints `Program exit with result 83`. To inspect its syntax tree
or build and run a native executable:

```sh
python3 src/compiler.py --ast tests/ok/practice7_members.txt
./full_compiler.sh tests/ok/practice7_members.txt
```

Programs using `read()` take integers from standard input:

```sh
python3 src/compiler.py tests/ok/practice7_io.txt output.ll
lli output.ll < tests/ok/practice7_io.in
```

## Language

```text
struct Point
{
    i32 mut x
    i32 mut y

    fn shift := (i32 dx) -> i32
    {
        x := x + dx
        exit x
    }
}
Point mut p{3, 4}
print(p.shift(2))
print(p)
exit p.x
```

- **Values:** `i32`, `i64`, `bool`, and structs. Variables and fields are
  const unless marked `mut`. An `i32` may widen to `i64`.
- **Expressions:** `+`, `-`, `*`, `==`, `!=`, and `!`. Multiplication binds
  tighter than addition and subtraction; one comparison is allowed per
  expression. `exit` takes a factor, such as a variable, field, or call.
- **Control flow:** `if`/`else` and `while`. Braces and `else` stand on their
  own lines. Blocks are nonempty scopes and may end with `exit`.
- **Structs:** fields precede member functions. Initializers supply fields in
  order, support nested braces, or copy an existing object. Field chains
  such as `c.center.x` can be read and assigned; assignment requires every
  link to be mutable. Replacing an object also requires all its fields to
  be mutable at every depth.
- **Functions:** `fn name := (type arg, ...) -> type`, with a body ending in
  `exit`. Parameters are const copies. Functions may call themselves or
  functions declared later; top-level variables are invisible inside them.
- **Member functions:** called on objects, as in `p.shift(2)`. Parameters
  and locals hide fields; unqualified calls prefer the struct's members
  over global functions. Methods receive the original object by address.
  Mutation is inferred through calls, including cycles; a mutating call
  requires every receiver link to be mutable.
- **Call chains:** struct results support further fields and member calls,
  such as `p.moved(1).shift(2)`. Results are temporary copies and may be
  mutated through member calls, but cannot be assignment targets. Calls
  are expressions and cannot stand alone as statements.
- **Input/output:** `read()` returns an `i32`. `print(value)` prints a number,
  `true`/`false`, a string literal, or a struct with its fields, followed by
  a newline. Strings have no escape sequences and are allowed only directly
  inside `print`. The names `read` and `print` are reserved.

A program contains struct declarations, then global functions, then
statements, and a final `exit`. See [grammar.ebnf](grammar.ebnf) for the
complete grammar and [tests/ok](tests/ok) for runnable examples.

## Testing

```sh
python3 check.py
```

The runner compiles fixtures, executes successful programs with `lli`,
compares complete output and optional AST snapshots, checks rejection
messages, and runs the Python unit tests, including native execution with
Clang and LLVM IR checks.

- `tests/ok/*.txt`: successful programs; neighboring `.expected` files hold
  complete stdout, including the final exit message.
- `tests/err/*.txt`: rejected programs; `.expected` files hold stderr with
  line and column positions.
- Optional `.in` files supply stdin; optional `.ast` files specify `--ast`
  output. Programs without `.in` receive empty stdin.
- `tests/valid` and `tests/invalid`: earlier fixtures retained as regression
  tests, using `.out` and `.err` expectations.

## Project layout

- `src/lexer.py` — byte lexer and source-positioned tokens.
- `src/parser.py` and `src/ast_nodes.py` — parser and syntax tree.
- `src/semantic.py` — name resolution, type checking, and mutation analysis.
- `src/compiler.py` — compiler CLI and LLVM IR generation.
- `grammar.ebnf` — language grammar.
- `check.py` and `tests/` — fixture runner and unit tests.
- `ai_usage.txt` — AI assistance record.
