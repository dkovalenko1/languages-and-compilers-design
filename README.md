# Practice 2 compiler

Use the VM from Practice 1 with its Python environment activated and `llvmlite`,
`llc`, and `clang` installed.

Compile and run example:

```sh
./full_compiler.sh tests/valid/worked_example.txt
```

Expected output: `Program exit with result 70`.

Generate LLVM IR only:

```sh
python3 compiler.py input.txt output.ll
```

Run tests:

```sh
python3 -m unittest discover -s tests -v
```
