# Practice 4 compiler

The hand-written byte lexer and recursive-descent parser build an AST. A
separate semantic visitor resolves declarations and types every expression
before the code-generation visitor builds LLVM IR with `llvmlite.ir`. The
grammar is in `grammar.ebnf`.

Declarations use `i32`, `i64`, or `bool`, and are const unless marked `mut`.
Arithmetic supports chains of `+`, `-`, and `*`; multiplication binds tighter.
One `==` or `!=` comparison may follow arithmetic and produces `bool`.
An `i32` value may widen to `i64`; other implicit conversions are errors.
`exit` accepts a constant or variable, including a boolean, but no operation.

Use the Ubuntu 24.04 VM from Practice 1, with `llvm`, `clang`, and a Python
3.10+ virtual environment containing the packages in `requirements.txt`.
Activate that environment before running the following commands.

```sh
python3 compiler.py --ast tests/ok/practice4_example.txt
python3 compiler.py tests/ok/practice4_example.txt output.ll
lli output.ll
./full_compiler.sh tests/ok/practice4_example.txt
python3 -m unittest discover -s tests -v
```

Both runs of the complete Practice 4 example print `Program exit with result
385`. The `tests/ok` and `tests/err` directories contain typed-language
programs and `.expected` results. Practice 2 and 3 fixtures remain in
`tests/valid` and `tests/invalid`, and their old outputs still pass.
