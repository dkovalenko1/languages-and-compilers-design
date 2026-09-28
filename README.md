# Practice 3 compiler

The hand-written byte lexer, recursive-descent parser, AST, and code-generation
visitor compile the course language to LLVM IR through `llvmlite.ir`. The
grammar is in `grammar.ebnf`. Expressions support chains of `+`, `-`, and `*`;
multiplication has higher precedence, and equal-precedence operators group
left to right. `exit` still accepts only a constant or variable.

Use the Ubuntu 24.04 VM from Practice 1, with `llvm`, `clang`, and a Python
3.10+ virtual environment containing the packages in `requirements.txt`.
Activate that environment before running the following commands.

```sh
python3 compiler.py --ast tests/valid/precedence_simple.txt
python3 compiler.py tests/valid/practice3_example.txt output.ll
lli output.ll
./full_compiler.sh tests/valid/practice3_example.txt
python3 -m unittest discover -s tests -v
```

Both runs of the complete example print `Program exit with result 120`.
The Practice 2 example remains available as `tests/valid/worked_example.txt`
and prints `Program exit with result 70`.
