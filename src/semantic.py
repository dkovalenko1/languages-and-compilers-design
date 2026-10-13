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
        # A stack of frames, source name -> declaration node. The program's
        # frame is at the bottom; every block pushes one and pops it on exit.
        self.scopes = [{}]

    def fail(self, node, message):
        raise CompileError(node.line, node.column, message)

    def lookup(self, node):
        """Resolve a use to the innermost declaration of its name."""
        for frame in reversed(self.scopes):
            if node.name in frame:
                return frame[node.name]
        self.fail(node, f"variable '{node.name}' is used before its declaration")

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

    def visit_block(self, node):
        self.scopes.append({})
        for statement in node.statements:
            statement.accept(self)
        if node.exit:
            node.exit.accept(self)
        self.scopes.pop()

    def check_condition(self, node, keyword: str):
        condition = node.condition.accept(self)
        if condition != "bool":
            self.fail(node, f"the condition of '{keyword}' must be bool, got {condition}")

    def visit_if(self, node):
        self.check_condition(node, "if")
        node.then_block.accept(self)
        if node.else_block:
            node.else_block.accept(self)

    def visit_while(self, node):
        self.check_condition(node, "while")
        node.body.accept(self)

    def visit_decl(self, node):
        # Only the innermost frame is checked: an outer name may be shadowed.
        frame = self.scopes[-1]
        if node.name in frame:
            where = "declared twice" if len(self.scopes) == 1 else "already declared in this block"
            self.fail(node, f"variable '{node.name}' is {where}")
        node.init.accept(self)  # The name is not in scope in its own initializer.
        self.check_assignable(node.init, node.type_name, node, f"initialise '{node.name}'")
        frame[node.name] = node

    def visit_assign(self, node):
        node.decl = self.lookup(node)
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

    def visit_not(self, node):
        operand = node.operand.accept(self)
        if operand != "bool":
            self.fail(node, f"cannot apply '!' to {operand}")
        node.type = "bool"
        return node.type

    def visit_var(self, node):
        node.decl = self.lookup(node)
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
