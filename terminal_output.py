"""Color CLI output only when writing to a terminal."""

import os
import sys


def print_colored(message, color, *, file=None):
    stream = sys.stdout if file is None else file
    text = str(message)
    if stream.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb":
        text = f"\033[{color}m{text}\033[0m"
    print(text, file=stream)


def print_error(message):
    print_colored(message, "31", file=sys.stderr)
