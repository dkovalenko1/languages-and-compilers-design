"""--remove-unused: drop declarations nobody reads and global functions nobody calls.

Uses are counted per node, through the links the checker put on every
variable (decl) and call (function), so two declarations named x are two
counters. Removing a declaration or a function takes the uses inside it with
it, so the pass repeats until a round removes nothing.
"""

from ast_nodes import (AssignNode, BlockNode, CallNode, DeclNode, FieldNode, FnNode, LambdaNode,
                       MemberCallNode, ProgramNode, ReadNode, VarNode)


def parts(node):
    """The children of a node, including the ones the dump leaves out."""
    if isinstance(node, LambdaNode):
        # The closure variable is not removable: walk its captures, not the declaration.
        return (node.struct, *node.decl.init.items)
    if isinstance(node, CallNode) and not isinstance(node, MemberCallNode) and hasattr(node, "receiver"):
        return (node.receiver, *node.args)  # c(5) reads c.
    return node.children()


def has_call_or_read(node) -> bool:
    """A call may print and read() consumes input, so a value with either is kept."""
    return isinstance(node, (CallNode, ReadNode)) or any(has_call_or_read(part) for part in parts(node))


def assigned(node: AssignNode):
    """The declaration an assignment writes: the root of p.x.y."""
    target = node.target
    while isinstance(target, FieldNode):
        target = target.base
    return target.decl


def count_uses(tree) -> dict[int, int]:
    """id(DeclNode) -> reads that resolve to it; id(global FnNode) -> calls of it."""
    uses = {}

    def use(node):
        uses[id(node)] = uses.get(id(node), 0) + 1

    def walk(node):
        if type(node) is FnNode:  # Member functions and lambda calls are MemberFnNode: kept.
            uses.setdefault(id(node), 0)
        elif isinstance(node, CallNode) and node.function.owner is None:
            use(node.function)  # Wherever it stands, also in another function's body.
        elif isinstance(node, DeclNode):
            uses.setdefault(id(node), 0)
            if has_call_or_read(node):
                use(node)
        elif isinstance(node, VarNode):
            use(node.decl)
        elif isinstance(node, AssignNode) and has_call_or_read(node.value):
            use(assigned(node))  # The target is not a read; its value may print.
        for part in parts(node):
            walk(part)

    walk(tree)
    return uses


def prune(node, dead: set[int]) -> int:
    """Drop the dead functions, declarations and assignments to them from every block."""
    removed = 0
    if isinstance(node, ProgramNode):
        kept = [function for function in node.functions if id(function) not in dead]
        removed = len(node.functions) - len(kept)
        node.functions = kept  # A function goes with its whole body.
    if isinstance(node, (ProgramNode, BlockNode)):
        kept = [statement for statement in node.statements
                if not (isinstance(statement, DeclNode) and id(statement) in dead
                        or isinstance(statement, AssignNode) and id(assigned(statement)) in dead)]
        removed += len(node.statements) - len(kept)
        node.statements = kept
    return removed + sum(prune(part, dead) for part in parts(node))


def remove_unused(tree):
    while True:
        dead = {node for node, count in count_uses(tree).items() if count == 0}
        if not prune(tree, dead):
            return tree
