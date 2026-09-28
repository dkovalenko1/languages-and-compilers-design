"""Source-positioned syntax tree for the compiler's language."""

from dataclasses import dataclass


@dataclass
class Node:
    line: int
    column: int

    def label(self) -> str:
        raise NotImplementedError

    def children(self) -> tuple["Node", ...]:
        return ()

    def dump(self, indent: int = 0) -> str:
        lines = [" " * indent + self.label()]
        for child in self.children():
            lines.append(child.dump(indent + 2))
        return "\n".join(lines)

    def accept(self, visitor):
        raise NotImplementedError


@dataclass
class StmtNode(Node):
    pass


@dataclass
class ExprNode(Node):
    pass


@dataclass
class ProgramNode(Node):
    statements: list[StmtNode]
    exit: "ExitNode"

    def label(self):
        return "Program"

    def children(self):
        return (*self.statements, self.exit)

    def accept(self, visitor):
        return visitor.visit_program(self)


@dataclass
class DeclNode(StmtNode):
    name: str
    type_name: str
    mutable: bool
    init: ExprNode

    def label(self):
        return f"Decl {self.name} {self.type_name} {'mut' if self.mutable else 'const'}"

    def children(self):
        return (self.init,)

    def accept(self, visitor):
        return visitor.visit_decl(self)


@dataclass
class AssignNode(StmtNode):
    name: str
    value: ExprNode

    def label(self):
        return f"Assign {self.name}"

    def children(self):
        return (self.value,)

    def accept(self, visitor):
        return visitor.visit_assign(self)


@dataclass
class ExitNode(Node):
    value: ExprNode

    def label(self):
        return "Exit"

    def children(self):
        return (self.value,)

    def accept(self, visitor):
        return visitor.visit_exit(self)


@dataclass
class BinOpNode(ExprNode):
    op: str
    left: ExprNode
    right: ExprNode

    def label(self):
        return f"BinOp {self.op}"

    def children(self):
        return (self.left, self.right)

    def accept(self, visitor):
        return visitor.visit_binop(self)


@dataclass
class VarNode(ExprNode):
    name: str

    def label(self):
        return f"Var {self.name}"

    def accept(self, visitor):
        return visitor.visit_var(self)


@dataclass
class ConstNode(ExprNode):
    value: str

    def label(self):
        return f"Const {self.value}"

    def accept(self, visitor):
        return visitor.visit_const(self)


@dataclass
class BoolNode(ExprNode):
    value: bool

    def label(self):
        return f"Bool {'true' if self.value else 'false'}"

    def accept(self, visitor):
        return visitor.visit_bool(self)
