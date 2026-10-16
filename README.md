# Practice 7 compiler

The hand-written byte lexer and recursive-descent parser build an AST. A
separate semantic visitor resolves declarations and types every expression
before the code-generation visitor builds LLVM IR with `llvmlite.ir`. The
grammar is in `grammar.ebnf`; the sources are in `src/`.

Declarations use `i32`, `i64`, `bool`, or a struct, and are const unless
marked `mut`. Arithmetic supports chains of `+`, `-`, and `*`; multiplication
binds tighter. One `==` or `!=` comparison may follow arithmetic and produces
`bool`, and `!` negates the factor right after it. An `i32` value may widen to
`i64`; other implicit conversions are errors. `exit` accepts a factor (a
constant, a variable, a field chain, a call, or `!` of one).

`if cond` and `while cond` stand on one line, followed by a block; `{`, `}`
and `else` stand alone on their lines, and a block is never empty. A block is
a scope: names declared in it may shadow outer names with any type and are
gone after its `}`. A block may end with `exit`. In the IR an `if` becomes
`then` / `else` / `merge` blocks and a `while` becomes `cond` / `body` / `end`
with a branch back to `cond`; every variable's `alloca` stands in its
function's entry block, so `opt -passes=mem2reg` promotes them to registers
and phis.

A program is its structs, then its functions, then its statements, then
`exit`. A struct field is a built-in type or a struct declared above, and is
const unless marked `mut`. `Point p{10, 20}` gives one value per field in
order, `Point q{p}` copies a whole object, and with nested braces
`Circle c{{10, 20}, 5}` builds an inner object in place. `c.center.x` reads a
field; a write through a chain needs the variable and every field on the way
to be `mut`, and replacing a whole object needs every field to be `mut` at
every depth. In the IR a struct is a named type such as
`%"Point" = type {i32, i32}`, an object is an `alloca` of it, a field is a
`gep` by the index the checker found, and an inner `{}` is built with
`insertvalue`.

`fn name := (type a, type b) -> type` declares a function; its block ends with
`exit`, which returns the result. A body sees its parameters (const copies),
its own variables and every function, but not the top-level variables. All
signatures are collected first, so a function may call itself or one declared
below it. Each function becomes `@"fn.name"` in the module, so a function
called `main` or `printf` does not clash with the runtime; its parameters are
stored into slots in its entry block, `exit` becomes `ret`, and a call
becomes `call`.

Use the Ubuntu 24.04 VM from Practice 1, with `llvm`, `clang`, and a Python
3.10+ virtual environment containing the packages in `requirements.txt`.
Activate that environment before running the following commands.

```sh
python3 src/compiler.py tests/ok/practice6_task2-check.txt output.ll && lli output.ll
python3 src/compiler.py tests/ok/practice6_task2-fib.txt output.ll && lli output.ll
python3 src/compiler.py --ast tests/ok/practice6_task3.txt
python3 src/compiler.py tests/ok/practice6_task3.txt output.ll && lli output.ll
python3 src/compiler.py tests/ok/struct_nested-init.txt output.ll && lli output.ll
python3 src/compiler.py tests/err/struct_const-link-write.txt output.ll
python3 src/compiler.py tests/ok/if-else_assign-both-arms.txt output.ll
opt -passes=mem2reg -S output.ll
./full_compiler.sh tests/ok/practice6_task3.txt
python3 check.py
```

The Task 2 programs print `true` and `55`, the Task 3 program prints `28`, the
nested-initialisation program prints `36`, and the rejected program reports
`line 14:1: cannot assign to 'c.center.x': 'c.center' is not mut`. In
`output.ll` of the Task 3 program, look for `%"Point" = type {i32, i32}`, a
`getelementptr inbounds %"Point"`, `define %"Point" @"fn.moved"` and
`call %"Point" @"fn.moved"`.

`check.py` compiles every fixture, runs the valid ones with `lli`, compares
stdout, `--ast` and error messages with the files next to them, runs the unit
tests in `tests/`, and prints one table row per program. `tests/ok` and
`tests/err` hold the typed-language programs with `.expected` results (and
`.ast` dumps for the Practice 5 programs and the Practice 6 Task 3 example).
The Practice 6 programs are named `practice6_*`, `struct_*`, `fn_*`,
`order_*` and `nested-init_*`. Practice 2 and 3 fixtures remain in
`tests/valid` and `tests/invalid`, and their old outputs still pass.

## Practice 7: member functions and input/output

A struct declares member functions after its fields (at least one field is
required). `p.shift(2)` and `c.center.d2()` are expressions, including after
`exit`; a call alone is not a statement. `--ast` shows `MemberFn` with its
parameters and body, and `MemberCall` with its receiver and arguments.

Inside a member, parameters and locals hide fields, and an unqualified call
checks the current struct's methods before global functions. Top-level
variables stay invisible. Methods that write their object's fields or call
mutating methods on the object/its fields are classified with a fixed-point
pass, including cycles. A mutating call requires every receiver link to be
`mut`; modifying a local copy does not make its owner's method mutating.

LLVM members have names such as `Point_shift` and receive the object pointer
as their first argument. Source global functions retain the `fn.` prefix,
and generated method names are uniqued if underscores make two spellings
coincide. Bare fields become GEP/load/store operations on the receiver.
Each compilation has its own LLVM context.

`read()` returns an i32 from stdin using scanf. `print(value)` is a statement
in every statement context: i32/i64 numbers, true/false, a literal, or a
struct recursively printed in field order. Literals have no escape sequences
and are only allowed directly in print. Text is passed through `%s`, so `%`
is preserved. Both names are reserved. Reads allocate storage in the entry
block even when called inside loops; print and the exit message share printf.

The additional task is included: a struct-valued call can be followed by
fields or member calls, including global call results. These values are
temporary copies: even mutating methods are allowed, including through a
const field of the temporary; assigning through a call result is rejected.
Reading a returned field uses extractvalue; calling a method stores the
result into a temporary entry-block slot and passes its address once.

### Tests and demonstration

The Practice 7 suite adds 12 tests/ok and 10 tests/err programs and focused
parameterized unit cases. `.txt` is source, `.expected` is complete stdout
for successful programs or stderr (with line:column) for errors. Optional
`.in` supplies stdin and `.ast` checks the parse tree. Both the lli runner
and native end-to-end unit runner pass `.in`, or empty stdin when absent.
The older fixtures remain regression tests.

Run these in the configured Python environment with LLVM on PATH:

```sh
python3 check.py
python3 src/compiler.py --ast tests/ok/practice7_members.txt
python3 src/compiler.py tests/ok/practice7_members.txt output.ll
lli output.ll
# Result 83; inspect Point_shift's pointer, GEP, load, add and store in output.ll.
python3 src/compiler.py tests/err/member_field_after.txt output.ll
python3 src/compiler.py tests/err/member_const_receiver.txt output.ll
python3 src/compiler.py tests/ok/practice7_io.txt output.ll
lli output.ll < tests/ok/practice7_io.in
python3 src/compiler.py tests/ok/practice7_chain.txt output.ll
lli output.ll
# Additional task: result 46.
```

Submit src/, tests/ and ai_usage.txt on branch practice-7, with a pull request
into main requesting vovaskochko as reviewer. Show the AST, result 83,
Point_shift IR, both rejection diagnostics, and the input/output example to
the teacher during practice or within three days.
