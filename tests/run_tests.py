"""Run with the Ubuntu venv: python3 tests/run_tests.py."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def run(*command):
    return subprocess.run(command, capture_output=True, text=True)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    count = 0
    with tempfile.TemporaryDirectory(prefix="practice1-tests-") as directory:
        build = Path(directory)
        for source in sorted((ROOT / "tests").glob("*.txt")):
            output = build / (source.stem + ".ll")
            result = run(sys.executable, str(ROOT / "compiler.py"), str(source), str(output))
            error_file = source.with_suffix(".err")
            if error_file.exists():
                check(result.returncode != 0, f"{source.name}: unexpectedly compiled")
                check(result.stderr == error_file.read_text(), f"{source.name}: {result.stderr!r}")
                check(result.stdout == "", f"{source.name}: unexpected stdout")
                check(not output.exists(), f"{source.name}: output created on error")
                # A failed compilation must also preserve a previous output.
                output.write_text("previous output\n")
                again = run(sys.executable, str(ROOT / "compiler.py"), str(source), str(output))
                check(again.returncode != 0 and output.read_text() == "previous output\n",
                      f"{source.name}: previous output changed on error")
            else:
                check(result.returncode == 0, f"{source.name}: {result.stderr}")
                obj = output.with_suffix(".o")
                program = build / source.stem
                compiled = run("llc", "-filetype=obj", "-relocation-model=pic",
                               str(output), "-o", str(obj))
                check(compiled.returncode == 0, compiled.stderr)
                linked = run("clang", "-fPIE", str(obj), "-o", str(program))
                check(linked.returncode == 0, linked.stderr)
                executed = run(str(program))
                expected = source.with_suffix(".out").read_text()
                check(executed.returncode == 0 and executed.stdout == expected
                      and executed.stderr == "", f"{source.name}: {executed}")
                interpreted = run("lli", str(output))
                check(interpreted.returncode == 0 and interpreted.stdout == expected,
                      f"{source.name}: lli failed: {interpreted.stderr}")
            count += 1
            print(f"PASS {source.stem}")
    print(f"{count} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
