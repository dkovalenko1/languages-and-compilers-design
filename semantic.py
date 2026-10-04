"""Resolve names and check types before any LLVM IR is constructed."""

from ast_nodes import ConstNode
from lexer import CompileError


I32_MAX = "2147483647"
I64_MAX = "9223372036854775807"
INTEGERS = {"i32", "i64"}


def fits(digits: str, limit: str) -> bool:
    return len(digits) < len(limit) or (len(digits) == len(limit) and digits <= limit)


class SemanticChecker:
    def __init__(self):
        self.symbols = {}  # Source name -> declaration node.

    def fail(self, node, message):
        raise CompileError(node.line, node.column, message)

    def require_declared(self, node):
        decl = self.symbols.get(node.name)
        if decl is None:
            self.fail(node, f"variable '{node.name}' is used before its declaration")
        return decl

    def check_assignable(self, expr, want: str, at, action: str):
        have = expr.type
        if have == want or (have == "i32" and want == "i64"):
            return
        if isinstance(expr, ConstNode) and have == "i64" and want == "i32":
            self.fail(expr, f"constant {expr.value} does not fit in i32")
        self.fail(at, f"cannot {action} of type {want} with a value of type {have}")

    def visit_program(self, node):
        for statement in node.statements:
            statement.accept(self)
        node.exit.accept(self)
        return node

    def visit_decl(self, node):
        if node.name in self.symbols:
            self.fail(node, f"variable '{node.name}' is declared twice")
        node.init.accept(self)  # The name is not in scope in its own initializer.
        self.check_assignable(node.init, node.type_name, node, f"initialise '{node.name}'")
        self.symbols[node.name] = node

    def visit_assign(self, node):
        node.decl = self.require_declared(node)
        if not node.decl.mutable:
            self.fail(node, f"cannot assign to '{node.name}': it is not mut")
        node.value.accept(self)
        self.check_assignable(node.value, node.decl.type_name, node, f"assign to '{node.name}'")

    def visit_exit(self, node):
        node.value.accept(self)

    def visit_binop(self, node):
        left = node.left.accept(self)
        right = node.right.accept(self)
        if node.op in ("+", "-", "*"):
            if left not in INTEGERS or right not in INTEGERS:
                self.fail(node, f"cannot apply '{node.op}' to bool")
            node.type = "i64" if "i64" in (left, right) else "i32"
        else:
            if not (left in INTEGERS and right in INTEGERS) and not (left == right == "bool"):
                self.fail(node, f"cannot compare {left} with {right}")
            node.type = "bool"
        return node.type

    def visit_var(self, node):
        node.decl = self.require_declared(node)
        node.type = node.decl.type_name
        return node.type

    def visit_const(self, node):
        digits = node.value.lstrip("0") or "0"
        if fits(digits, I32_MAX):
            node.type = "i32"
        elif fits(digits, I64_MAX):
            node.type = "i64"
        else:
            self.fail(node, f"constant {node.value} does not fit in i64")
        return node.type

    def visit_bool(self, node):
        node.type = "bool"
        return node.type
