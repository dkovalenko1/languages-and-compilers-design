"""Resolve names and check types before any LLVM IR is constructed."""

from ast_nodes import ConstNode, DeclNode, FieldNode, InitNode, ParamNode, path
from lexer import CompileError


I32_MAX = "2147483647"
I64_MAX = "9223372036854775807"
INTEGERS = {"i32", "i64"}
BUILTINS = {"i32", "i64", "bool"}


def fits(digits: str, limit: str) -> bool:
    return len(digits) < len(limit) or (len(digits) == len(limit) and digits <= limit)


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


class SemanticChecker:
    def __init__(self):
        # A stack of frames, source name -> declaration node. The program's
        # frame is at the bottom; every block pushes one and pops it on exit.
        # A function body starts from a stack of its own, so it cannot see
        # the top-level variables.
        self.scopes = [{}]
        self.structs = {}  # Struct name -> StructNode, in declaration order.
        self.functions = {}  # Function name -> FnNode, collected before any body.
        self.function = None  # The FnNode whose body is checked, or None at the top level.
        self.top_level_names = set()  # Only for a clearer error inside a function.

    def fail(self, node, message):
        raise CompileError(node.line, node.column, message)

    def lookup(self, node):
        """Resolve a use to the innermost declaration of its name."""
        for frame in reversed(self.scopes):
            if node.name in frame:
                return frame[node.name]
        if self.function is not None and node.name in self.top_level_names:
            self.fail(node, f"variable '{node.name}' is not visible inside function '{self.function.name}'")
        self.fail(node, f"variable '{node.name}' is used before its declaration")

    def check_type(self, type_name: str, node, line=None, column=None):
        if type_name not in BUILTINS and type_name not in self.structs:
            raise CompileError(line or node.line, column or node.column, f"unknown type '{type_name}'")

    def check_assignable(self, expr, want: str, at, action: str):
        have = expr.type
        if have == want or (have == "i32" and want == "i64"):
            return
        if isinstance(expr, ConstNode) and have == "i64" and want == "i32":
            self.fail(expr, f"constant {expr.value} does not fit in i32")
        self.fail(at, f"cannot {action} of type {want} with a value of type {have}")

    def check_variable_name(self, node):
        if node.name in self.functions:
            self.fail(node, f"'{node.name}' is already the name of a function")

    def const_field(self, type_name: str):
        """Return 'Struct.field' of the first const field at any depth, or None."""
        struct = self.structs.get(type_name)
        for field in struct.fields if struct else ():
            if not field.mutable:
                return f"{type_name}.{field.name}"
            if (inner := self.const_field(field.type_name)) is not None:
                return inner
        return None

    def visit_program(self, node):
        self.top_level_names = {s.name for s in node.statements if isinstance(s, DeclNode)}
        for struct in node.structs:
            struct.accept(self)
        # Every signature is known before any body, so a body may call a
        # function declared below it, or itself.
        for function in node.functions:
            if function.name in self.functions:
                self.fail(function, f"function '{function.name}' is declared twice")
            for param in function.params:
                self.check_type(param.type_name, param)
            self.check_type(function.result_type, function)
            self.functions[function.name] = function
        for function in node.functions:
            function.accept(self)
        for statement in node.statements:
            statement.accept(self)
        node.exit.accept(self)
        return node

    def visit_struct(self, node):
        if node.name in self.structs:
            self.fail(node, f"struct '{node.name}' is declared twice")
        names = set()
        for field in node.fields:
            if field.name in names:
                self.fail(field, f"field '{field.name}' is declared twice in '{node.name}'")
            names.add(field.name)
            if field.type_name == node.name:
                self.fail(field, f"struct '{node.name}' cannot contain itself")
            self.check_type(field.type_name, field)  # Only the structs above are known.
        self.structs[node.name] = node

    def visit_fn(self, node):
        outer_scopes, self.scopes, self.function = self.scopes, [{}], node
        frame = self.scopes[0]
        for param in node.params:
            self.check_variable_name(param)
            if param.name in frame:
                self.fail(param, f"parameter '{param.name}' is declared twice")
            frame[param.name] = param
        node.body.accept(self)
        self.scopes, self.function = outer_scopes, None

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
        self.check_type(node.type_name, node, node.type_line, node.type_column)
        self.check_variable_name(node)
        # Only the innermost frame is checked: an outer name may be shadowed.
        frame = self.scopes[-1]
        if node.name in frame:
            where = "declared twice" if len(self.scopes) == 1 else "already declared in this block"
            self.fail(node, f"variable '{node.name}' is {where}")
        # The name is not in scope in its own initializer.
        if node.type_name in self.structs:
            self.check_init(node.init, node.type_name)
        else:
            if len(node.init.items) != 1:
                self.fail(node.init, f"'{node.name}' of type {node.type_name} takes one value, "
                                     f"but {len(node.init.items)} are given")
            value = node.init.items[0]
            if isinstance(value, InitNode):
                self.fail(value, f"a {{}} cannot initialise '{node.name}' of type {node.type_name}")
            value.accept(self)
            self.check_assignable(value, node.type_name, node, f"initialise '{node.name}'")
        frame[node.name] = node

    def check_init(self, init, struct_name: str):
        """One value per field in order, or one value of the struct's own type (a copy)."""
        fields = self.structs[struct_name].fields
        items = init.items
        if len(items) == 1 and not isinstance(items[0], InitNode):
            if items[0].accept(self) == struct_name:
                init.copy = True
                return
            if len(fields) != 1:
                self.fail(init, f"'{struct_name}' has {plural(len(fields), 'field')}, but 1 value is given")
        elif len(items) != len(fields):
            self.fail(init, f"'{struct_name}' has {plural(len(fields), 'field')}, "
                            f"but {plural(len(items), 'value')} {'is' if len(items) == 1 else 'are'} given")
        for item, field in zip(items, fields):
            if isinstance(item, InitNode):
                if field.type_name not in self.structs:
                    self.fail(item, f"a {{}} cannot initialise field '{struct_name}.{field.name}' "
                                    f"of type {field.type_name}")
                self.check_init(item, field.type_name)
                continue
            if item.type is None:  # The single value above is typed already.
                item.accept(self)
            self.check_assignable(item, field.type_name, item,
                                  f"initialise field '{struct_name}.{field.name}'")

    def visit_assign(self, node):
        """Every link of the chain must be mut: the variable and each field on the way."""
        target = node.target
        target.accept(self)
        links = []
        while isinstance(target, FieldNode):
            links.append(target)
            target = target.base
        root = target.decl
        written = path(node.target)
        if isinstance(root, ParamNode):
            self.fail(node, f"cannot assign to '{written}': '{node.name}' is a parameter")
        if not root.mutable:
            if not links:
                self.fail(node, f"cannot assign to '{node.name}': it is not mut")
            self.fail(node, f"cannot assign to '{written}': '{node.name}' is not mut")
        for link in reversed(links):
            if not self.structs[link.base.type].fields[link.index].mutable:
                self.fail(node, f"cannot assign to '{written}': '{path(link)}' is not mut")
        # A whole object replaces every field, so each must be mut at any depth.
        if (const := self.const_field(node.target.type)) is not None:
            self.fail(node, f"cannot assign to '{written}': field '{const}' is not mut")
        node.value.accept(self)
        self.check_assignable(node.value, node.target.type, node, f"assign to '{written}'")

    def visit_exit(self, node):
        have = node.value.accept(self)
        if self.function is not None:
            want = self.function.result_type
            if not (have == want or (have == "i32" and want == "i64")):
                self.fail(node.value, f"function '{self.function.name}' must exit with {want}, "
                                      f"got {have}")
        elif have not in BUILTINS:
            self.fail(node.value, f"the program must exit with i32, i64 or bool, got {have}")

    def visit_binop(self, node):
        left = node.left.accept(self)
        right = node.right.accept(self)
        if node.op in ("+", "-", "*"):
            for operand in (left, right):
                if operand not in INTEGERS:
                    self.fail(node, f"cannot apply '{node.op}' to {operand}")
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

    def visit_field(self, node):
        """Find the field's index here, so the code generator never looks a name up."""
        base = node.base.accept(self)
        struct = self.structs.get(base)
        if struct is None:
            self.fail(node, f"'{path(node.base)}' is {base}, it has no field '{node.name}'")
        for index, field in enumerate(struct.fields):
            if field.name == node.name:
                node.index, node.type = index, field.type_name
                return node.type
        self.fail(node, f"struct '{base}' has no field '{node.name}'")

    def visit_call(self, node):
        function = node.function = self.functions.get(node.name)
        if function is None:
            self.fail(node, f"unknown function '{node.name}'")
        if len(node.args) != len(function.params):
            self.fail(node, f"function '{node.name}' takes {plural(len(function.params), 'argument')}, "
                            f"but {len(node.args)} {'is' if len(node.args) == 1 else 'are'} given")
        for number, (arg, param) in enumerate(zip(node.args, function.params), start=1):
            have = arg.accept(self)
            if not (have == param.type_name or (have == "i32" and param.type_name == "i64")):
                self.fail(arg, f"argument {number} of '{node.name}' must be {param.type_name}, got {have}")
        node.type = function.result_type
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
