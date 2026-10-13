#!/usr/bin/env bash
# Compile a source program to LLVM IR, build it, and run it.
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 input.txt" >&2
    exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
build_dir="$(mktemp -d)"
trap 'rm -rf -- "$build_dir"' EXIT

# Uses the activated Python environment, or an explicit PYTHON executable.
"${PYTHON:-python3}" -B "$script_dir/src/compiler.py" "$1" "$build_dir/output.ll"

llc -filetype=obj -relocation-model=pic "$build_dir/output.ll" -o "$build_dir/output.o"
clang -fPIE "$build_dir/output.o" -o "$build_dir/program"
"$build_dir/program"
