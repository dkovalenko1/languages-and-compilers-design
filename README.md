# Practice 5 compiler

The hand-written byte lexer and recursive-descent parser build an AST. A
separate semantic visitor resolves declarations and types every expression
before the code-generation visitor builds LLVM IR with `llvmlite.ir`. The
grammar is in `grammar.ebnf`; the sources are in `src/`.

Declarations use `i32`, `i64`, or `bool`, and are const unless marked `mut`.
Arithmetic supports chains of `+`, `-`, and `*`; multiplication binds tighter.
One `==` or `!=` comparison may follow arithmetic and produces `bool`, and `!`
negates the factor right after it. An `i32` value may widen to `i64`; other
implicit conversions are errors. `exit` accepts a factor (a constant, a
variable, or `!` of one), including a boolean.

`if cond` and `while cond` stand on one line, followed by a block; `{`, `}`
and `else` stand alone on their lines, and a block is never empty. A block is
a scope: names declared in it may shadow outer names with any type and are
gone after its `}`. A block may end with `exit`. In the IR an `if` becomes
`then` / `else` / `merge` blocks and a `while` becomes `cond` / `body` / `end`
with a branch back to `cond`; every variable's `alloca` stands in the entry
block, so `opt -passes=mem2reg` promotes them to registers and phis.

Use the Ubuntu 24.04 VM from Practice 1, with `llvm`, `clang`, and a Python
3.10+ virtual environment containing the packages in `requirements.txt`.
Activate that environment before running the following commands.

```sh
python3 src/compiler.py --ast tests/ok/scope_warm-up.txt
python3 src/compiler.py tests/ok/scope_warm-up.txt output.ll
lli output.ll
python3 src/compiler.py tests/ok/if-else_assign-both-arms.txt output.ll
opt -passes=mem2reg -S output.ll
./full_compiler.sh tests/ok/if-else_example.txt
python3 check.py
```

The warm-up program prints `Program exit with result 20`, the if/else
example prints `15`, and `opt` shows `%r.0 = phi i32 [ 1, %then ], [ 2,
%else ]` in `merge`.

`check.py` compiles every fixture, runs the valid ones with `lli`, compares
stdout, `--ast` and error messages with the files next to them, runs the unit
tests in `tests/`, and prints one table row per program. `tests/ok` and
`tests/err` hold the typed-language programs with `.expected` results (and
`.ast` dumps for the Practice 5 programs). Practice 2 and 3 fixtures remain in
`tests/valid` and `tests/invalid`, and their old outputs still pass.
