"""Run every fixture program through the compiler and lli, and print a table.

tests/ok, tests/valid    compile, run with lli, compare stdout with .expected / .out;
                         a .ast file next to the program is compared with --ast
tests/err, tests/invalid compilation must fail with the stderr in .expected / .err
                         and must not write the output file
Then the unit tests in tests/ run once and add one row.

Exit status 0 only when every row passes. LLI=/path/to/lli overrides the tool.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
COMPILER = ROOT / "src" / "compiler.py"
TESTS = ROOT / "tests"
LLI = os.environ.get("LLI", "lli")

# (directory, should compile, expected-output suffix)
SUITES = [
    ("ok", True, ".expected"),
    ("valid", True, ".out"),
    ("err", False, ".expected"),
    ("invalid", False, ".err"),
]


def run(command):
    return subprocess.run(command, capture_output=True, text=True)


def compiler(*args):
    return run([sys.executable, "-B", str(COMPILER), *args])


def check_valid(source: Path, expected: Path, directory: Path) -> str | None:
    """Return None when the program passes, or a one-line reason."""
    output = directory / "output.ll"
    result = compiler(str(source), str(output))
    if result.returncode != 0:
        return "did not compile: " + result.stderr.strip()
    executed = run([LLI, str(output)])
    if executed.returncode != 0:
        return f"lli exited with {executed.returncode}: {executed.stderr.strip()}"
    if executed.stdout != expected.read_text():
        return f"printed {executed.stdout.strip()!r}"
    tree = source.with_suffix(".ast")
    if tree.exists():
        dumped = compiler("--ast", str(source))
        if dumped.stdout != tree.read_text():
            return "--ast differs from " + tree.name
    return None


def check_invalid(source: Path, expected: Path, directory: Path) -> str | None:
    output = directory / "output.ll"
    result = compiler(str(source), str(output))
    if result.returncode == 0:
        return "compiled, but must be rejected"
    if output.exists():
        return "wrote output.ll despite the error"
    if result.stderr != expected.read_text():
        return "reported " + result.stderr.strip()
    return None


def first_line(path: Path) -> str:
    text = path.read_text().strip()
    return text.splitlines()[0] if text else ""


def main() -> int:
    if shutil.which(LLI) is None:
        print(f"check.py: '{LLI}' not found; install LLVM or set LLI", file=sys.stderr)
        return 2
    rows, failures = [], 0
    for name, valid, suffix in SUITES:
        for source in sorted((TESTS / name).glob("*.txt")):
            expected = source.with_suffix(suffix)
            with tempfile.TemporaryDirectory() as directory:
                check = check_valid if valid else check_invalid
                reason = check(source, expected, Path(directory))
            failures += reason is not None
            detail = first_line(expected) if reason is None else reason
            rows.append((name, source.stem, "PASS" if reason is None else "FAIL", detail))

    unit = run([sys.executable, "-B", "-m", "unittest", "discover", "-s", str(TESTS)])
    summary = unit.stderr.strip().splitlines()
    ran = next((line for line in summary if line.startswith("Ran ")), "no tests ran")
    unit_ok = unit.returncode == 0
    failures += not unit_ok
    rows.append(("unittest", "tests/test_*.py", "PASS" if unit_ok else "FAIL",
                 ran if unit_ok else summary[-1]))

    widths = [max(len(row[i]) for row in rows + [("suite", "program", "result", "")])
              for i in range(3)]
    header = ("suite", "program", "result", "output")
    for row in [header, tuple("-" * w for w in widths) + ("-" * 6,), *rows]:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)), row[3])
    print(f"\n{len(rows) - failures}/{len(rows)} passed")
    if not unit_ok:
        print(unit.stderr, file=sys.stderr)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
