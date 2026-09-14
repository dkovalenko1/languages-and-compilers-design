import argparse
from dataclasses import dataclass
from pathlib import Path
import sys


KEYWORDS = {b"i32": "type", b"mut": "specifier", b"exit": "exit"}
SINGLE_BYTE = {
    ord("{"): "lbrace", ord("}"): "rbrace",
    ord("+"): "plus", ord("-"): "minus", ord("*"): "star",
}


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    line: int
    column: int


class CompileError(Exception):
    def __init__(self, line, column, message):
        super().__init__(f"compilation error: line {line}:{column}: {message}")


def is_alpha(b):
    return 65 <= b <= 90 or 97 <= b <= 122 or b == 95


def is_digit(b):
    return 48 <= b <= 57


def lex(data: bytes) -> list[list[Token]]:
    """Return tokens grouped by source line; line boundaries represent newlines.

    Spaces and tabs are discarded. Positions count bytes, starting at one.
    Only a byte ending an identifier or number is re-read in START.
    """
    lines, tokens = [], []
    state, start, line, col = "START", 0, 1, 1
    start_line, start_col = 1, 1
    open_braces = []
    i = 0
    while i <= len(data):
        b = data[i] if i < len(data) else None
        if state == "START":
            if b is None or b == 10:
                if open_braces:
                    opening_line, opening_col = open_braces[0]
                    raise CompileError(opening_line, opening_col,
                                    "'{' is not closed before the end of the line")
                if b is None:
                    break
                lines.append(tokens)
                tokens = []
                line += 1
                col = 0
            elif b in (32, 9):
                pass
            elif is_alpha(b) or is_digit(b):
                state = "IDENT" if is_alpha(b) else "NUMBER"
                start, start_line, start_col = i, line, col
            elif b == ord(":"):
                state, start_line, start_col = "ASSIGN", line, col
            elif b in SINGLE_BYTE:
                tokens.append(Token(SINGLE_BYTE[b], chr(b), line, col))
                if b == ord("{"):
                    open_braces.append((line, col))
                elif b == ord("}") and open_braces:
                    open_braces.pop()
            else:
                byte_text = repr(chr(b)) if 32 <= b <= 126 else f"0x{b:02x}"
                raise CompileError(line, col, f"unexpected byte {byte_text}")
        elif state == "IDENT":
            if b is not None and (is_alpha(b) or is_digit(b)):
                pass
            else:
                word = data[start:i]
                tokens.append(Token(KEYWORDS.get(word, "ident"), word.decode("ascii"),
                                    start_line, start_col))
                state = "START"
                continue
        elif state == "NUMBER":
            if b is not None and is_digit(b):
                pass
            elif b is not None and is_alpha(b):
                raise CompileError(start_line, start_col, "a number cannot contain letters or '_'")
            else:
                tokens.append(Token("number", data[start:i].decode("ascii"),
                                    start_line, start_col))
                state = "START"
                continue
        elif state == "ASSIGN":
            if b != ord("="):
                raise CompileError(start_line, start_col, "':' must be followed by '='")
            tokens.append(Token("assign", ":=", start_line, start_col))
            state = "START"
        i += 1
        col += 1
    if tokens:
        lines.append(tokens)
    return lines


def main():
    parser = argparse.ArgumentParser(description="Print the Practice 2 lexer tokens")
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    try:
        lines = lex(args.source.read_bytes())
    except (CompileError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    for tokens in lines:
        for token in tokens:
            print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
