"""--remove-unused: drop declarations nobody reads, on the checked tree.

Reads are counted per declaration, through the decl link the checker put on
every variable node, so two declarations named x are two counters. Removing a
declaration takes the reads in its initialiser with it, so the pass repeats
until a round removes nothing.
"""

from ast_nodes import (AssignNode, BlockNode, CallNode, DeclNode, FieldNode, LambdaNode,
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


def count_reads(tree) -> dict[int, int]:
    """id(DeclNode) -> number of reads that resolve to it."""
    reads = {}

    def read(decl):
        reads[id(decl)] = reads.get(id(decl), 0) + 1

    def walk(node):
        if isinstance(node, DeclNode):
            reads.setdefault(id(node), 0)
            if has_call_or_read(node):
                read(node)
        elif isinstance(node, VarNode):
            read(node.decl)
        elif isinstance(node, AssignNode) and has_call_or_read(node.value):
            read(assigned(node))  # The target is not a read; its value may print.
        for part in parts(node):
            walk(part)

    walk(tree)
    return reads


def prune(node, dead: set[int]) -> int:
    """Drop the dead declarations and the assignments to them from every block."""
    removed = 0
    if isinstance(node, (ProgramNode, BlockNode)):
        kept = [statement for statement in node.statements
                if not (isinstance(statement, DeclNode) and id(statement) in dead
                        or isinstance(statement, AssignNode) and id(assigned(statement)) in dead)]
        removed = len(node.statements) - len(kept)
        node.statements = kept
    return removed + sum(prune(part, dead) for part in parts(node))


def remove_unused(tree):
    while True:
        dead = {decl for decl, count in count_reads(tree).items() if count == 0}
        if not prune(tree, dead):
            return tree
