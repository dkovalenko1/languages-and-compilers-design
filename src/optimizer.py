"""--remove-unused: drop declarations nobody reads and global functions nobody calls.

Uses are counted per node, through the links the checker put on every
variable (decl) and call (function), so two declarations named x are two
counters. Removing a declaration or a function takes the uses inside it with
it, so the pass repeats until a round removes nothing.

A value that may be observed keeps its variable even with no reads: read(),
or a call of a function with an effect. Which functions have one is computed
once, before the loop: removals only take away calls of functions without one.
"""

from ast_nodes import (AssignNode, BlockNode, CallNode, DeclNode, FieldNode, FnNode, LambdaNode,
                       MemberCallNode, PrintNode, ProgramNode, ReadNode, VarNode, WhileNode)


def parts(node):
    """The children of a node, including the ones the dump leaves out."""
    if isinstance(node, LambdaNode):
        # The closure variable is not removable: walk its captures, not the declaration.
        return (node.struct, *node.decl.init.items)
    if isinstance(node, CallNode) and not isinstance(node, MemberCallNode) and hasattr(node, "receiver"):
        return (node.receiver, *node.args)  # c(5) reads c.
    return node.children()


def nodes(node):
    """node and every node under it."""
    yield node
    for part in parts(node):
        yield from nodes(part)


def reachable(callees: dict[int, set[int]], start: int) -> set[int]:
    """Every function a call of start may reach, through any number of calls."""
    seen, stack = set(), [*callees[start]]
    while stack:
        function = stack.pop()
        if function not in seen:
            seen.add(function)
            stack.extend(callees.get(function, ()))
    return seen


def effectful(tree) -> set[int]:
    """id of every function whose call may be observed.

    It prints or reads, changes the object it is called on, may not return
    (a while, or a call that comes back to itself), or calls such a function.
    """
    functions = [*tree.functions, *(method for struct in [*tree.structs, *tree.lambdas]
                                    for method in struct.methods)]
    callees, found = {}, set()
    for function in functions:
        body = list(nodes(function.body))  # With the bodies of lambdas declared there: kept if in doubt.
        callees[id(function)] = {id(node.function) for node in body if isinstance(node, CallNode)}
        if function.mutating or any(isinstance(node, (PrintNode, ReadNode, WhileNode)) for node in body):
            found.add(id(function))
    found |= {id(function) for function in functions if id(function) in reachable(callees, id(function))}
    changed = True
    while changed:  # A caller of a function with an effect has one; cycles need the fixpoint.
        changed = False
        for function, called in callees.items():
            if function not in found and called & found:
                found.add(function)
                changed = True
    return found


def has_effect(node, effects: set[int]) -> bool:
    """read() consumes input and an effectful call may print or change an object."""
    if isinstance(node, ReadNode) or isinstance(node, CallNode) and id(node.function) in effects:
        return True
    return any(has_effect(part, effects) for part in parts(node))


def assigned(node: AssignNode):
    """The declaration an assignment writes: the root of p.x.y."""
    target = node.target
    while isinstance(target, FieldNode):
        target = target.base
    return target.decl


def count_uses(tree, effects: set[int]) -> dict[int, int]:
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
            if has_effect(node, effects):
                use(node)
        elif isinstance(node, VarNode):
            use(node.decl)
        elif isinstance(node, AssignNode) and has_effect(node.value, effects):
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
    effects = effectful(tree)
    while True:
        dead = {node for node, count in count_uses(tree, effects).items() if count == 0}
        if not prune(tree, dead):
            return tree
