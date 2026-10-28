"""Recursive-descent parser over the lexer's per-line token vectors.

Two cursors: a line cursor (peek_line / next_line) walks the non-blank lines,
and a token cursor (peek / eat) walks the current line. A statement is one
line, except an if or a while, which also consumes the lines of its blocks.
A struct or a function declaration consumes its header line and its body.
"""

from ast_nodes import (
    AssignNode, BinOpNode, BlockNode, BoolNode, CallNode, ConstNode, DeclNode,
    ExitNode, FieldDeclNode, FieldNode, FnNode, IfNode, InitNode, NotNode,
    ParamNode, ProgramNode, StructNode, VarNode, WhileNode,
    MemberFnNode, MemberCallNode, PrintNode, ReadNode, StringNode,
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
        if kind == "ident" and token.text in ("read", "print"):
            raise self.error(f"'{token.text}' is reserved")
        return self.eat()

    def finish_line(self):
        token = self.peek()
        if token is not None:
            raise self.error(f"unexpected '{token.text}' after the statement")

    def parse_program(self) -> ProgramNode:  # program ::= { struct } { fn } { statement } exit
        structs, functions, statements = [], [], []
        while (tokens := self.peek_line()) is not None and tokens[0].kind != "exit":
            first = tokens[0]
            if first.kind == "struct":
                if functions or statements:
                    after = "a statement" if statements else "a function"
                    raise CompileError(first.line, first.column, f"struct declared after {after}")
                structs.append(self.parse_struct())
            elif first.kind == "fn":
                if statements:
                    raise CompileError(first.line, first.column, "function declared after a statement")
                functions.append(self.parse_fn())
            else:
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
        return ProgramNode(1, 1, structs, functions, statements, exit_node)

    def parse_statement(self):  # statement ::= decl | assign | if | while | print
        """Consume one line, or for an if or a while, every line up to the end of its last block."""
        token = self.next_line()[0]
        if token.text == "print":
            statement = self.parse_print()
            self.finish_line()
            return statement
        if token.kind == "if":
            return self.parse_if()
        if token.kind == "while":
            return self.parse_while()
        if token.kind == "type":
            statement = self.parse_decl()
        elif token.kind == "ident" and len(self.tokens) > 1 and self.tokens[1].kind in ("ident", "specifier"):
            statement = self.parse_decl()  # A struct type: Point p{...}
        elif token.kind == "ident":
            statement = self.parse_assign()
        elif token.kind in ("struct", "fn"):
            what = "a struct" if token.kind == "struct" else "a function"
            raise self.error(f"{what} can be declared only at the top level")
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

    def parse_block(self, owner: str, exit_required: str | None = None) -> BlockNode:
        """block ::= "{" NL { statement } [ exit NL ] "}" NL, and not empty.

        exit_required is the error for a block that must end with exit.
        """
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
        closing = self.eat()
        self.finish_line()
        if not statements and exit_node is None:
            raise self.error("empty block", brace)
        if exit_required and exit_node is None:
            raise self.error(exit_required, closing)
        return BlockNode(brace.line, brace.column, statements, exit_node)

    def parse_struct(self) -> StructNode:
        """Fields precede optional member functions; at least one field is required."""
        self.next_line()
        keyword = self.eat()
        name = self.expect("ident", "expected a struct name after 'struct'")
        self.finish_line()
        header = f"struct {name.text}"
        tokens = self.peek_line()
        if tokens is None:
            raise self.error(f"expected '{{' on its own line after '{header}', found end of file")
        if tokens[0].kind != "lbrace":
            raise CompileError(tokens[0].line, tokens[0].column,
                               f"expected '{{' on its own line after '{header}', got '{tokens[0].text}'")
        self.next_line()
        brace = self.eat()
        self.finish_line()
        fields, methods = [], []
        while True:
            tokens = self.peek_line()
            if tokens is None:
                raise self.error("'{' is never closed", brace)
            if tokens[0].kind == "rbrace":
                break
            if tokens[0].kind == "fn":
                if not fields:
                    raise self.error("a member function must follow at least one field", tokens[0])
                method = self.parse_fn(member=True)
                method.owner = name.text
                methods.append(method)
                continue
            if methods:
                raise self.error("a field must precede member functions", tokens[0])
            self.next_line()  # field_decl ::= type [ "mut" ] ident NL
            type_token = self.parse_type("expected a field type")
            mutable = self.peek() is not None and self.peek().kind == "specifier"
            if mutable:
                self.eat()
            field_name = self.expect("ident", "expected a field name")
            self.finish_line()
            fields.append(FieldDeclNode(field_name.line, field_name.column, field_name.text,
                                        type_token.text, mutable))
        self.next_line()
        self.eat()
        self.finish_line()
        if not fields:
            raise self.error(f"struct '{name.text}' needs at least one field", brace)
        return StructNode(keyword.line, keyword.column, name.text, fields, methods)

    def parse_fn(self, member=False) -> FnNode:
        """fn ::= "fn" ident ":=" "(" [ type ident { "," type ident } ] ")" "->" type NL block"""
        self.next_line()
        self.eat()
        name = self.expect("ident", "expected a function name after 'fn'")
        self.expect("assign", f"expected ':=' after 'fn {name.text}'")
        self.expect("lparen", "expected '(' before the parameters")
        params = []
        if self.peek() is not None and self.peek().kind != "rparen":
            while True:
                type_token = self.parse_type("expected a parameter type")
                param = self.expect("ident", "expected a parameter name")
                params.append(ParamNode(param.line, param.column, param.text, type_token.text))
                if self.peek() is None or self.peek().kind != "comma":
                    break
                self.eat()
        self.expect("rparen", "expected ',' or ')' after a parameter")
        self.expect("arrow", "expected '->' and the result type after ')'")
        result = self.parse_type("expected the result type after '->'")
        self.finish_line()
        body = self.parse_block("fn", f"the body of '{name.text}' must end with exit")
        cls = MemberFnNode if member else FnNode
        return cls(name.line, name.column, name.text, params, result.text, body)

    def parse_type(self, message: str) -> Token:  # type ::= "i32" | "i64" | "bool" | ident
        token = self.peek()
        if token is None or token.kind not in ("type", "ident"):
            raise self.error(message)
        return self.eat()

    def parse_decl(self) -> DeclNode:  # decl ::= type [ "mut" ] ident "{" value { "," value } "}"
        type_token = self.eat()
        mutable = self.peek() is not None and self.peek().kind == "specifier"
        if mutable:
            self.eat()
        name = self.expect("ident", "expected a variable name")
        if self.peek() is None or self.peek().kind != "lbrace":
            raise self.error(f"variable '{name.text}' needs an initialiser in {{}}",
                             name if self.peek() is None else None)
        init = self.parse_init()
        return DeclNode(name.line, name.column, name.text, type_token.text, mutable, init,
                        type_token.line, type_token.column)

    def parse_init(self) -> InitNode:  # init ::= "{" value { "," value } "}" ; value ::= expr | init
        brace = self.eat()
        items = []
        while True:
            token = self.peek()
            items.append(self.parse_init() if token is not None and token.kind == "lbrace"
                         else self.parse_expr())
            if self.peek() is None:
                raise self.error("expected '}', found end of line")
            if self.peek().kind != "comma":
                break
            self.eat()
        self.expect("rbrace", "expected '}' after the initialiser")
        return InitNode(brace.line, brace.column, items)

    def parse_assign(self) -> AssignNode:
        name = self.eat()
        target = self.parse_chain(name)
        token = self.peek()
        current = target
        while isinstance(current, FieldNode):
            current = current.base
        if isinstance(current, CallNode):
            if token is not None and token.kind == "assign":
                raise self.error("cannot assign to a temporary call result", name)
            raise self.error("a call is not a statement", name)
        self.expect("assign", f"expected ':=' after '{name.text}'")
        return AssignNode(name.line, name.column, name.text, target, self.parse_expr())

    def parse_chain(self, name: Token):
        if name.text in ("read", "print"):
            raise self.error(f"'{name.text}' is reserved", name)
        node = (self.parse_call(name) if self.peek() is not None and self.peek().kind == "lparen"
                else VarNode(name.line, name.column, name.text))
        return self.parse_postfix(node)

    def parse_postfix(self, node):
        while self.peek() is not None and self.peek().kind == "dot":
            dot = self.eat()
            name = self.expect("ident", "expected a field or member function name after '.'")
            if self.peek() is not None and self.peek().kind == "lparen":
                node = self.parse_call(name, node)
            else:
                node = FieldNode(name.line, name.column, node, name.text)
            node.dot_column = dot.column
        return node

    def parse_call(self, name: Token, receiver=None):
        self.eat()
        args = []
        if self.peek() is not None and self.peek().kind != "rparen":
            while True:
                args.append(self.parse_expr())
                if self.peek() is None or self.peek().kind != "comma":
                    break
                self.eat()
        self.expect("rparen", "expected ',' or ')' after an argument")
        if receiver is not None:
            return MemberCallNode(name.line, name.column, name.text, args, receiver)
        return CallNode(name.line, name.column, name.text, args)

    def parse_print(self):
        keyword = self.eat()
        self.expect("lparen", "expected '(' after print")
        if self.peek() is None or self.peek().kind == "rparen":
            raise self.error("print takes exactly one argument", keyword)
        if self.peek().kind == "string":
            token = self.eat()
            value = StringNode(token.line, token.column, token.text)
        else:
            value = self.parse_expr()
        if self.peek() is not None and self.peek().kind == "comma":
            raise self.error("print takes exactly one argument", keyword)
        self.expect("rparen", "expected ')' after print argument")
        return PrintNode(keyword.line, keyword.column, value)

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

    def parse_factor(self):  # factor ::= number | "true" | "false" | ident | field | call | "!" factor
        token = self.peek()
        if token is None:
            raise self.error("expected a constant or a variable, found end of line")
        if token.kind == "number":
            self.eat()
            return ConstNode(token.line, token.column, token.text)
        if token.kind == "ident":
            self.eat()
            if token.text == "print":
                raise self.error("print has no value", token)
            if token.text == "read":
                if self.peek() is None or self.peek().kind != "lparen":
                    raise self.error("'read' is reserved", token)
                call = self.parse_call(token)
                if call.args:
                    raise self.error("read takes no arguments", token)
                return self.parse_postfix(ReadNode(token.line, token.column))
            return self.parse_chain(token)
        if token.kind == "string":
            raise self.error("a string literal is only allowed directly inside print")
        if token.kind == "boolean":
            self.eat()
            return BoolNode(token.line, token.column, token.text == "true")
        if token.kind == "not":
            self.eat()
            return NotNode(token.line, token.column, self.parse_factor())
        raise self.error(f"expected a constant or a variable, got '{token.text}'")
