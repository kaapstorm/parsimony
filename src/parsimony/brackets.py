"""Exploding bracketed containers one element per line."""

import libcst as cst
from libcst.metadata import CodeRange, PositionProvider

from parsimony.core import Reindenter, parenthesized_ws, span

# Node types that carry an explodable comma-separated child list. The name
# is kept for continuity though a FunctionDef header is not a literal bracket
# pair -- a def's parens are implicit.
BRACKETED = (
    cst.Call,
    cst.List,
    cst.Tuple,
    cst.Set,
    cst.Dict,
    cst.Subscript,
    cst.FunctionDef,
    cst.ClassDef,
)

# Where each type's comma-separated children live, in source order. A slot is
# ``(attribute_name, is_sequence)``. An absent optional slot holds
# ``MaybeSentinel.DEFAULT`` or ``None`` -- never a ``CSTNode`` -- so the one
# presence test ``isinstance(value, cst.CSTNode)`` covers all of them.
#
# Keyed on cst.Parameters rather than cst.FunctionDef because that is where a
# def's slots actually live; _slot_container bridges the difference.
_SLOTS = {
    cst.Call: (('args', True),),
    cst.List: (('elements', True),),
    cst.Tuple: (('elements', True),),
    cst.Set: (('elements', True),),
    cst.Dict: (('elements', True),),
    cst.Subscript: (('slice', True),),
    cst.ClassDef: (('bases', True), ('keywords', True)),
    cst.Parameters: (
        ('posonly_params', True),
        ('posonly_ind', False),
        ('params', True),
        ('star_arg', False),
        ('kwonly_params', True),
        ('star_kwarg', False),
    ),
}

# Where the whitespace just inside the opening bracket lives. An int step
# indexes a sequence; a str step names an attribute.
_OPEN_WS = {
    cst.Call: ('whitespace_before_args',),
    cst.FunctionDef: ('whitespace_before_params',),
    cst.List: ('lbracket', 'whitespace_after'),
    cst.Subscript: ('lbracket', 'whitespace_after'),
    cst.Set: ('lbrace', 'whitespace_after'),
    cst.Dict: ('lbrace', 'whitespace_after'),
    cst.ClassDef: ('lpar', 'whitespace_after'),
    cst.Tuple: ('lpar', 0, 'whitespace_after'),
}


def _slot_container(node):
    """The node whose attribute slots hold the comma-separated children."""
    if isinstance(node, cst.FunctionDef):
        return node.params
    return node


def _with_slot_container(node, container):
    """The inverse of ``_slot_container``: put ``container`` on ``node``."""
    if isinstance(node, cst.FunctionDef):
        return node.with_changes(params=container)
    return container


def flatten_slots(container):
    """Return ``(children, plan)`` for a slot container.

    ``children`` are the comma-carrying elements in source order. ``plan``
    records how many children came from each slot, so ``unflatten_slots``
    can put them back without re-deriving the occupancy: both halves read
    the one description in ``_SLOTS`` instead of mirroring each other by
    hand.
    """
    children = []
    plan = []
    for name, is_sequence in _SLOTS[type(container)]:
        value = getattr(container, name)
        if is_sequence:
            got = list(value)
        else:
            got = [value] if isinstance(value, cst.CSTNode) else []
        children.extend(got)
        plan.append((name, is_sequence, len(got)))
    return children, plan


def unflatten_slots(container, plan, children):
    """Write ``children`` back into the slots recorded by ``plan``."""
    changes = {}
    it = iter(children)
    for name, is_sequence, count in plan:
        taken = [next(it) for _ in range(count)]
        if is_sequence:
            changes[name] = taken
        elif taken:
            changes[name] = taken[0]
        # An absent optional slot keeps its MaybeSentinel.DEFAULT / None.
    return container.with_changes(**changes)


def children_of(node):
    """Return the comma-separated children for an explodable node."""
    children, _plan = flatten_slots(_slot_container(node))
    return children


def is_multi_item(node):
    return len(children_of(node)) >= 2


def is_explodable(node):
    """A bare tuple (`a, b` with no parens) has no bracket to open. A class
    with no base list (`class Bar:`) likewise has no parens to open."""
    if isinstance(node, cst.Tuple):
        return bool(node.lpar)
    if isinstance(node, cst.ClassDef):
        return isinstance(node.lpar, cst.LeftParen)
    return True


def _path_get(obj, path):
    for step in path:
        obj = obj[step] if isinstance(step, int) else getattr(obj, step)
    return obj


def _path_set(obj, path, value):
    step, rest = path[0], path[1:]
    if rest:
        value = _path_set(_path_get(obj, (step,)), rest, value)
    if isinstance(step, int):
        seq = list(obj)
        seq[step] = value
        return seq
    return obj.with_changes(**{step: value})


def _open_ws(node):
    """The whitespace just inside a node's opening bracket, or ``None`` if
    it has no bracket to open (a bare tuple, a paren-less class).

    The ``is_explodable`` guard is load-bearing: ``BracketCollector`` asks
    ``_already_exploded`` about every BRACKETED node, including the
    bracket-less ones, whose ``lpar`` would not survive the path walk.
    """
    if not is_explodable(node):
        return None
    return _path_get(node, _OPEN_WS[type(node)])


def _set_open_ws(node, ws):
    """Return ``node`` with ``ws`` just inside its opening bracket."""
    return _path_set(node, _OPEN_WS[type(node)], ws)


def explode_bracket(node, inner, outer):
    """Return ``node`` with its children split one-per-line.

    Exploding moves every child from the opening line to ``inner``, one
    INDENT deeper, so any breaks a child already carries are shifted by
    the same amount to keep them aligned under their new position. This
    is the reindent ``break_chain`` does for the same reason.

    The reindent is applied to each CHILD, not to the node: a def/class
    node spans its whole body, and reindenting that would shift every
    pre-existing break in the body -- code we must never touch. Applying
    it per child is equivalent for the expression cases, because the
    node's only other whitespace slots (the opening whitespace, and each
    comma's ``whitespace_after``) are overwritten below anyway.
    """
    delta = len(inner) - len(outer)
    container = _slot_container(node)
    kids, plan = flatten_slots(container)
    new_kids = []
    for i, kid in enumerate(kids):
        kid = kid.visit(Reindenter(delta))
        last = i == len(kids) - 1
        whitespace_after = parenthesized_ws(outer if last else inner)
        comma = cst.Comma(whitespace_after=whitespace_after)
        new_kids.append(kid.with_changes(comma=comma))

    container = unflatten_slots(container, plan, new_kids)
    node = _with_slot_container(node, container)
    return _set_open_ws(node, parenthesized_ws(inner))


def header_pos(get_metadata, node):
    """The position of a node's explodable region.

    For most nodes this is the node's own span. A def/class node spans the
    whole body, so we return only the header: the parameter list for a
    FunctionDef, the paren range for a ClassDef. This keeps the indent,
    over-long-line intersection and span-matching correct.
    """
    if isinstance(node, cst.FunctionDef):
        return get_metadata(PositionProvider, node.params)
    if isinstance(node, cst.ClassDef):
        if not isinstance(node.lpar, cst.LeftParen):
            return get_metadata(PositionProvider, node)
        lpar = get_metadata(PositionProvider, node.lpar)
        rpar = get_metadata(PositionProvider, node.rpar)
        return CodeRange(start=lpar.start, end=rpar.end)
    return get_metadata(PositionProvider, node)


def _already_exploded(node):
    """True if a node's own bracket already carries a line break.

    Scoped to the node's own header: the opening whitespace, and the commas
    of its direct children. A line break inside a *nested* bracket does not
    count -- that was the old whole-node ``code_for_node`` test, which
    reported an unbroken header as exploded whenever anything inside it was
    broken, and so left over-long lines unfixed.
    """
    def is_paren_space(space):
        return isinstance(space, cst.ParenthesizedWhitespace)

    if is_paren_space(_open_ws(node)):
        return True
    return any(
        is_paren_space(getattr(kid.comma, 'whitespace_after', None))
        for kid in children_of(node)
    )


class BracketExploder(cst.CSTTransformer):
    """Explode the single node whose full span matches `target`.

    Matching the full (start, end) span -- not just the start -- matters
    for chained calls: every call in ``a.b().c()`` shares a start position
    (the leftmost token), so a start-only match would explode them all.
    """

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, target, inner, outer):
        self.target = target  # (start_line, start_col, end_line, end_col)
        self.inner = inner
        self.outer = outer

    def _maybe(self, original, updated):
        pos = header_pos(self.get_metadata, original)
        if span(pos) == self.target:
            return explode_bracket(updated, self.inner, self.outer)
        return updated

    def leave_Call(self, original_node, updated_node):
        return self._maybe(original_node, updated_node)

    def leave_List(self, original_node, updated_node):
        return self._maybe(original_node, updated_node)

    def leave_Tuple(self, original_node, updated_node):
        return self._maybe(original_node, updated_node)

    def leave_Set(self, original_node, updated_node):
        return self._maybe(original_node, updated_node)

    def leave_Dict(self, original_node, updated_node):
        return self._maybe(original_node, updated_node)

    def leave_Subscript(self, original_node, updated_node):
        return self._maybe(original_node, updated_node)

    def leave_ClassDef(self, original_node, updated_node):
        if not isinstance(original_node.lpar, cst.LeftParen):
            return updated_node
        return self._maybe(original_node, updated_node)

    def leave_FunctionDef(self, original_node, updated_node):
        return self._maybe(original_node, updated_node)


class BracketCollector(cst.CSTVisitor):
    """Collect bracketed nodes with their position, depth and number of
    arguments."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self):
        self.found = []
        self.depth = 0

    def on_visit(self, node):
        if isinstance(node, cst.FormattedString):
            # Brackets inside an f-string are string content, not code:
            # exploding them would corrupt the literal. Don't descend.
            return False
        if isinstance(node, BRACKETED):
            pos = header_pos(self.get_metadata, node)
            already = _already_exploded(node)
            self.found.append(
                {
                    'pos': pos,
                    'depth': self.depth,
                    'multi': is_multi_item(node) if not already else False,
                    'exploded': already,
                    'explodable': is_explodable(node),
                }
            )
            self.depth += 1
        return True

    def on_leave(self, original_node):
        if isinstance(original_node, BRACKETED):
            self.depth -= 1
