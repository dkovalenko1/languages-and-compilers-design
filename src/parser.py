"""Recursive-descent parser over the lexer's per-line token vectors.

Two cursors: a line cursor (peek_line / next_line) walks the non-blank lines,
and a token cursor (peek / eat) walks the current line. A statement is one
line, except an if or a while, which also consumes the lines of its blocks.
"""

from ast_nodes import (
    AssignNode, BinOpNode, BlockNode, BoolNode, ConstNode, DeclNode, ExitNode,
    IfNode, NotNode, ProgramNode, VarNode, WhileNode,
)
from lexer import CompileError, Token


class Parser:
    def __init__(self, lines: list[list[Token]]):
        self.lines = [tokens for tokens in lines if tokens]  # Blank lines carry nothing.
        self.line_index = 0
        self.tokens: list[Token] = []
        self.index = 0

    def peek_line(self) -> list[Token] | None:
        return self.lines[self.line_index] if self.line_index < len(self.lines) else None

    def next_line(self) -> list[Token]:
        self.tokens, self.index = self.lines[self.line_index], 0
        self.line_index += 1
        return self.tokens

    def peek(self) -> Token | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def eat(self) -> Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def error(self, message: str, at: Token | None = None) -> CompileError:
        token = at or self.peek()
        if token is not None:
            return CompileError(token.line, token.column, message)
        last = self.tokens[-1]
        return CompileError(last.line, last.column + len(last.text), message)

    def expect(self, kind: str, message: str) -> Token:
        token = self.peek()
        if token is None or token.kind != kind:
            raise self.error(message)
        return self.eat()

    def finish_line(self):
        token = self.peek()
        if token is not None:
            raise self.error(f"unexpected '{token.text}' after the statement")

    def parse_program(self) -> ProgramNode:  # program ::= { statement } exit
        statements = []
        while (tokens := self.peek_line()) is not None and tokens[0].kind != "exit":
            statements.append(self.parse_statement())
        if tokens is None:
            if not self.tokens:
                raise CompileError(1, 1, "missing exit statement")
            last = self.tokens[-1]
            raise CompileError(last.line, last.column, "missing exit statement")
        self.next_line()
        exit_node = self.parse_exit()
        if (tokens := self.peek_line()) is not None:
            raise CompileError(tokens[0].line, tokens[0].column, "exit must be the last statement")
        return ProgramNode(1, 1, statements, exit_node)

    def parse_statement(self):  # statement ::= decl | assign | if | while
        """Consume one line, or for an if or a while, every line up to the end of its last block."""
        token = self.next_line()[0]
        if token.kind == "if":
            return self.parse_if()
        if token.kind == "while":
            return self.parse_while()
        if token.kind == "type":
            statement = self.parse_decl()
        elif token.kind == "ident":
            statement = self.parse_assign()
        elif token.kind == "else":
            raise self.error("'else' without an 'if'")
        elif token.kind == "rbrace":
            raise self.error("'}' without a matching '{'")
        else:
            raise self.error(f"cannot start a statement with '{token.text}'")
        self.finish_line()
        return statement

    def parse_if(self) -> IfNode:  # if ::= "if" expr NL block [ "else" NL block ]
        keyword = self.eat()
        condition = self.parse_expr()
        self.finish_line()
        then_block = self.parse_block("if")
        else_block = None
        if (tokens := self.peek_line()) is not None and tokens[0].kind == "else":
            self.next_line()
            self.eat()
            self.finish_line()
            else_block = self.parse_block("else")
        return IfNode(keyword.line, keyword.column, condition, then_block, else_block)

    def parse_while(self) -> WhileNode:  # while ::= "while" expr NL block
        keyword = self.eat()
        condition = self.parse_expr()
        self.finish_line()
        return WhileNode(keyword.line, keyword.column, condition, self.parse_block("while"))

    def parse_block(self, owner: str) -> BlockNode:
        """block ::= "{" NL { statement } [ exit NL ] "}" NL, and not empty."""
        tokens = self.peek_line()
        if tokens is None:
            raise self.error(f"expected '{{' on its own line after '{owner}', found end of file")
        if tokens[0].kind != "lbrace":
            raise CompileError(tokens[0].line, tokens[0].column,
                               f"expected '{{' on its own line after '{owner}', got '{tokens[0].text}'")
        self.next_line()
        brace = self.eat()
        self.finish_line()
        statements, exit_node = [], None
        while True:
            tokens = self.peek_line()
            if tokens is None:
                raise self.error("'{' is never closed", brace)
            first = tokens[0]
            if first.kind == "rbrace":
                break
            if exit_node is not None:
                raise CompileError(first.line, first.column, "statement after 'exit' in the same block")
            if first.kind == "exit":
                self.next_line()
                exit_node = self.parse_exit()
            else:
                statements.append(self.parse_statement())
        self.next_line()
        self.eat()
        self.finish_line()
        if not statements and exit_node is None:
            raise self.error("empty block", brace)
        return BlockNode(brace.line, brace.column, statements, exit_node)

    def parse_decl(self) -> DeclNode:
        type_name = self.eat().text
        mutable = self.peek() is not None and self.peek().kind == "specifier"
        if mutable:
            self.eat()
        name = self.expect("ident", "expected a variable name")
        if self.peek() is None:
            raise self.error(f"variable '{name.text}' needs an initialiser in {{}}", name)
        self.expect("lbrace", f"variable '{name.text}' needs an initialiser in {{}}")
        init = self.parse_expr()
        if self.peek() is None:
            raise self.error("expected '}', found end of line")
        self.expect("rbrace", "expected '}' after the initialiser")
        return DeclNode(name.line, name.column, name.text, type_name, mutable, init)

    def parse_assign(self) -> AssignNode:
        name = self.eat()
        self.expect("assign", f"expected ':=' after '{name.text}'")
        return AssignNode(name.line, name.column, name.text, self.parse_expr())

    def parse_exit(self) -> ExitNode:
        keyword = self.eat()
        node = ExitNode(keyword.line, keyword.column, self.parse_factor())
        self.finish_line()
        return node

    def parse_expr(self):
        node = self.parse_arith()
        token = self.peek()
        if token is not None and token.kind in ("eq", "ne"):
            self.eat()
            node = BinOpNode(token.line, token.column, token.text, node, self.parse_arith())
            if (token := self.peek()) is not None and token.kind in ("eq", "ne"):
                raise self.error("only one comparison is allowed per expression")
        return node

    def parse_arith(self):
        node = self.parse_term()
        while (token := self.peek()) is not None and token.kind in ("plus", "minus"):
            self.eat()
            node = BinOpNode(token.line, token.column, token.text, node, self.parse_term())
        return node

    def parse_term(self):
        node = self.parse_factor()
        while (token := self.peek()) is not None and token.kind == "star":
            self.eat()
            node = BinOpNode(token.line, token.column, token.text, node, self.parse_factor())
        return node

    def parse_factor(self):  # factor ::= number | "true" | "false" | ident | "!" factor
        token = self.peek()
        if token is None:
            raise self.error("expected a constant or a variable, found end of line")
        if token.kind == "number":
            self.eat()
            return ConstNode(token.line, token.column, token.text)
        if token.kind == "ident":
            self.eat()
            return VarNode(token.line, token.column, token.text)
        if token.kind == "boolean":
            self.eat()
            return BoolNode(token.line, token.column, token.text == "true")
        if token.kind == "not":
            self.eat()
            return NotNode(token.line, token.column, self.parse_factor())
        raise self.error(f"expected a constant or a variable, got '{token.text}'")
