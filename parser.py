"""Recursive-descent parser over the lexer's per-line token vectors."""

from ast_nodes import AssignNode, BinOpNode, ConstNode, DeclNode, ExitNode, ProgramNode, VarNode
from lexer import CompileError, Token


class Parser:
    def __init__(self, lines: list[list[Token]]):
        self.lines = lines
        self.tokens: list[Token] = []
        self.index = 0

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

    def parse_program(self) -> ProgramNode:
        statements = []
        exit_node = None
        last_token = None
        for tokens in self.lines:
            if not tokens:
                continue
            self.tokens, self.index = tokens, 0
            if exit_node is not None:
                raise self.error("exit must be the last statement")
            if tokens[0].kind == "exit":
                exit_node = self.parse_exit()
            else:
                statements.append(self.parse_statement())
            self.finish_line()
            last_token = tokens[-1]
        if exit_node is None:
            if last_token is None:
                raise CompileError(1, 1, "missing exit statement")
            raise CompileError(last_token.line, last_token.column, "missing exit statement")
        return ProgramNode(1, 1, statements, exit_node)

    def parse_statement(self):
        token = self.peek()
        if token.kind == "type":
            return self.parse_decl()
        if token.kind == "ident":
            return self.parse_assign()
        raise self.error(f"cannot start a statement with '{token.text}'")

    def parse_decl(self) -> DeclNode:
        self.eat()  # i32
        mutable = self.peek() is not None and self.peek().kind == "specifier"
        if mutable:
            self.eat()
        name = self.expect("ident", "expected a variable name")
        if self.peek() is None:
            raise self.error(f"variable '{name.text}' needs an initialiser in {{}}", name)
        self.expect("lbrace", f"variable '{name.text}' needs an initialiser in {{}}")
        init = self.parse_expr()
        self.expect("rbrace", "expected '}' after the initialiser")
        return DeclNode(name.line, name.column, name.text, mutable, init)

    def parse_assign(self) -> AssignNode:
        name = self.eat()
        self.expect("assign", f"expected ':=' after '{name.text}'")
        return AssignNode(name.line, name.column, name.text, self.parse_expr())

    def parse_exit(self) -> ExitNode:
        keyword = self.eat()
        return ExitNode(keyword.line, keyword.column, self.parse_factor())

    def parse_expr(self):
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

    def parse_factor(self):
        token = self.peek()
        if token is None:
            raise self.error("expected a constant or a variable, found end of line")
        if token.kind == "number":
            self.eat()
            return ConstNode(token.line, token.column, token.text)
        if token.kind == "ident":
            self.eat()
            return VarNode(token.line, token.column, token.text)
        raise self.error(f"expected a constant or a variable, got '{token.text}'")
