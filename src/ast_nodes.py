"""Source-positioned syntax tree for the compiler's language."""

from dataclasses import dataclass, field


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
    type: str | None = field(default=None, init=False, repr=False)


@dataclass
class ProgramNode(Node):
    """program ::= { struct } { fn } { statement } exit"""

    structs: list["StructNode"]
    functions: list["FnNode"]
    statements: list[StmtNode]
    exit: "ExitNode"

    def label(self):
        return "Program"

    def children(self):
        return (*self.structs, *self.functions, *self.statements, self.exit)

    def accept(self, visitor):
        return visitor.visit_program(self)


@dataclass
class FieldDeclNode(Node):
    name: str
    type_name: str
    mutable: bool

    def label(self):
        return f"FieldDecl {self.name} {self.type_name} {'mut' if self.mutable else 'const'}"


@dataclass
class StructNode(Node):
    name: str
    fields: list[FieldDeclNode]

    def label(self):
        return f"Struct {self.name}"

    def children(self):
        return tuple(self.fields)

    def accept(self, visitor):
        return visitor.visit_struct(self)


@dataclass
class ParamNode(Node):
    """A parameter is a const variable of the function body."""

    name: str
    type_name: str
    mutable: bool = field(default=False, init=False)


@dataclass
class FnNode(Node):
    name: str
    params: list[ParamNode]
    result_type: str
    body: "BlockNode"

    def label(self):
        params = ", ".join(f"{param.type_name} {param.name}" for param in self.params)
        return f"Fn {self.name} ({params}) -> {self.result_type}"

    def children(self):
        return (self.body,)

    def accept(self, visitor):
        return visitor.visit_fn(self)


@dataclass
class InitNode(Node):
    """The values between '{' and '}': one per field, or a single value.

    The position is the '{'. A value may be another InitNode for a struct field.
    """

    items: list["ExprNode | InitNode"]
    copy: bool = field(default=False, init=False, repr=False)  # One value of the struct's own type.

    def label(self):
        return "Init"

    def children(self):
        return tuple(self.items)


@dataclass
class DeclNode(StmtNode):
    name: str
    type_name: str
    mutable: bool
    init: InitNode
    type_line: int = field(default=0, repr=False)
    type_column: int = field(default=0, repr=False)

    def label(self):
        return f"Decl {self.name} {self.type_name} {'mut' if self.mutable else 'const'}"

    def children(self):
        return tuple(self.init.items)

    def accept(self, visitor):
        return visitor.visit_decl(self)


@dataclass
class AssignNode(StmtNode):
    """target is a VarNode or a FieldNode chain that starts at the assigned variable."""

    name: str
    target: "VarNode | FieldNode"
    value: ExprNode

    def label(self):
        return f"Assign {path(self.target)}"

    def children(self):
        return (self.value,)

    def accept(self, visitor):
        return visitor.visit_assign(self)


@dataclass
class BlockNode(Node):
    """Lines between '{' and '}': a scope of its own, ending with an optional exit."""

    statements: list[StmtNode]
    exit: "ExitNode | None"

    def label(self):
        return "Block"

    def children(self):
        return (*self.statements, self.exit) if self.exit else tuple(self.statements)

    def accept(self, visitor):
        return visitor.visit_block(self)


@dataclass
class IfNode(StmtNode):
    condition: ExprNode
    then_block: BlockNode
    else_block: BlockNode | None

    def label(self):
        return "If"

    def children(self):
        blocks = (self.then_block, self.else_block) if self.else_block else (self.then_block,)
        return (self.condition, *blocks)

    def accept(self, visitor):
        return visitor.visit_if(self)


@dataclass
class WhileNode(StmtNode):
    condition: ExprNode
    body: BlockNode

    def label(self):
        return "While"

    def children(self):
        return (self.condition, self.body)

    def accept(self, visitor):
        return visitor.visit_while(self)


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
class NotNode(ExprNode):
    operand: ExprNode

    def label(self):
        return "Not"

    def children(self):
        return (self.operand,)

    def accept(self, visitor):
        return visitor.visit_not(self)


@dataclass
class VarNode(ExprNode):
    name: str
    decl: DeclNode | ParamNode | None = field(default=None, init=False, repr=False)

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


@dataclass
class FieldNode(ExprNode):
    """base.name; the position is the field name. The checker sets index."""

    base: "VarNode | FieldNode"
    name: str
    index: int | None = field(default=None, init=False, repr=False)

    def label(self):
        return f"Field {self.name}"

    def children(self):
        return (self.base,)

    def accept(self, visitor):
        return visitor.visit_field(self)


@dataclass
class CallNode(ExprNode):
    name: str
    args: list[ExprNode]
    function: FnNode | None = field(default=None, init=False, repr=False)

    def label(self):
        return f"Call {self.name}"

    def children(self):
        return tuple(self.args)

    def accept(self, visitor):
        return visitor.visit_call(self)


def path(node: "VarNode | FieldNode") -> str:
    """The source text of a field chain: c.center.x."""
    if isinstance(node, FieldNode):
        return f"{path(node.base)}.{node.name}"
    return node.name
