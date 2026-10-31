"""Run every fixture program through the compiler and lli, and print a table.

tests/ok, tests/valid    compile, run with lli, compare stdout with .expected / .out;
                         a .ast file next to the program is compared with --ast,
                         a .checked file with --ast-checked
tests/err, tests/invalid compilation must fail with the stderr in .expected / .err
                         and must not write the output file
tests/opt                the output in .expected must be the same with and without
                         --remove-unused; .astc holds --remove-unused --ast-checked
Then the unit tests in tests/ run once and add one row.

Exit status 0 only when every row passes. LLI=/path/to/lli overrides the tool.
REMOVE_UNUSED=1 compiles every earlier program with --remove-unused; the
.checked snapshots, which show the tree before the pass, are skipped then.
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
FLAGS = ["--remove-unused"] if os.environ.get("REMOVE_UNUSED") else []


def run(command, timeout=60, input=None):
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, input=input)


def compiler(*args):
    return run([sys.executable, "-B", str(COMPILER), *args])


def check_valid(source: Path, expected: Path, directory: Path, flags=FLAGS) -> str | None:
    """Return None when the program passes, or a one-line reason."""
    output = directory / "output.ll"
    result = compiler(*flags, str(source), str(output))
    if result.returncode != 0:
        return "did not compile: " + result.stderr.strip()
    try:
        stdin = source.with_suffix(".in")
        executed = run([LLI, str(output)], timeout=10,
                       input=stdin.read_text() if stdin.exists() else "")
    except subprocess.TimeoutExpired:
        return "lli did not finish within 10 seconds"
    if executed.returncode != 0:
        return f"lli exited with {executed.returncode}: {executed.stderr.strip()}"
    if executed.stdout != expected.read_text():
        return f"printed {executed.stdout.strip()!r}"
    tree = source.with_suffix(".ast")
    if tree.exists():
        dumped = compiler("--ast", str(source))
        if dumped.stdout != tree.read_text():
            return "--ast differs from " + tree.name
    checked = source.with_suffix(".checked")
    if not flags and checked.exists() and compiler("--ast-checked", str(source)).stdout != checked.read_text():
        return "--ast-checked differs from " + checked.name
    return None


def check_invalid(source: Path, expected: Path, directory: Path) -> str | None:
    output = directory / "output.ll"
    result = compiler(*FLAGS, str(source), str(output))
    if result.returncode == 0:
        return "compiled, but must be rejected"
    if output.exists():
        return "wrote output.ll despite the error"
    if result.stderr != expected.read_text():
        return "reported " + result.stderr.strip()
    return None


def check_opt(source: Path, expected: Path, directory: Path) -> str | None:
    for flags in ([], ["--remove-unused"]):
        if (reason := check_valid(source, expected, directory, flags)) is not None:
            return f"{' '.join(flags) or 'without the flag'}: {reason}"
    tree = compiler("--remove-unused", "--ast-checked", str(source)).stdout
    if tree != source.with_suffix(".astc").read_text():
        return "--remove-unused --ast-checked differs from " + source.stem + ".astc"
    return None


# (directory, check, expected-output suffix)
SUITES = [
    ("ok", check_valid, ".expected"),
    ("valid", check_valid, ".out"),
    ("err", check_invalid, ".expected"),
    ("invalid", check_invalid, ".err"),
    ("opt", check_opt, ".expected"),
]


def first_line(path: Path) -> str:
    text = path.read_text().strip()
    return text.splitlines()[0] if text else ""


def main() -> int:
    if shutil.which(LLI) is None:
        print(f"check.py: '{LLI}' not found; install LLVM or set LLI", file=sys.stderr)
        return 2
    rows, failures = [], 0
    for name, check, suffix in SUITES:
        for source in sorted((TESTS / name).glob("*.txt")):
            expected = source.with_suffix(suffix)
            with tempfile.TemporaryDirectory() as directory:
                reason = check(source, expected, Path(directory))
            failures += reason is not None
            detail = first_line(expected) if reason is None else reason
            rows.append((name, source.stem, "PASS" if reason is None else "FAIL", detail))

    unit = run([sys.executable, "-B", "-m", "unittest", "discover", "-s", str(TESTS)], timeout=600)
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
