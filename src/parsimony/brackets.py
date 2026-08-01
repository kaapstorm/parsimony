"""Exploding bracketed containers one element per line."""

import libcst as cst
from libcst.metadata import PositionProvider

from parsimony.core import parenthesized_ws, span

# Node types that carry an explodable comma-separated child list.
BRACKETED = (cst.Call, cst.List, cst.Tuple, cst.Set, cst.Dict, cst.Subscript)

# Where each type's comma-separated children live, in source order. A slot is
# ``(attribute_name, is_sequence)``.
_SLOTS = {
    cst.Call: (('args', True),),
    cst.List: (('elements', True),),
    cst.Tuple: (('elements', True),),
    cst.Set: (('elements', True),),
    cst.Dict: (('elements', True),),
    cst.Subscript: (('slice', True),),
}

# Where the whitespace just inside the opening bracket lives. An int step
# indexes a sequence; a str step names an attribute.
_OPEN_WS = {
    cst.Call: ('whitespace_before_args',),
    cst.List: ('lbracket', 'whitespace_after'),
    cst.Subscript: ('lbracket', 'whitespace_after'),
    cst.Set: ('lbrace', 'whitespace_after'),
    cst.Dict: ('lbrace', 'whitespace_after'),
    cst.Tuple: ('lpar', 0, 'whitespace_after'),
}


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
    children, _plan = flatten_slots(node)
    return children


def is_multi_item(node):
    return len(children_of(node)) >= 2


def is_explodable(node):
    """A bare tuple (`a, b` with no parens) has no bracket to open."""
    if isinstance(node, cst.Tuple):
        return bool(node.lpar)
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
    it has no bracket to open (a bare tuple)."""
    if not is_explodable(node):
        return None
    return _path_get(node, _OPEN_WS[type(node)])


def _set_open_ws(node, ws):
    """Return ``node`` with ``ws`` just inside its opening bracket."""
    return _path_set(node, _OPEN_WS[type(node)], ws)


def explode_bracket(node, inner, outer):
    """Return ``node`` with its children split one-per-line."""
    kids, plan = flatten_slots(node)
    new_kids = []
    for i, kid in enumerate(kids):
        last = i == len(kids) - 1
        whitespace_after = parenthesized_ws(outer if last else inner)
        comma = cst.Comma(whitespace_after=whitespace_after)
        new_kids.append(kid.with_changes(comma=comma))

    node = unflatten_slots(node, plan, new_kids)
    return _set_open_ws(node, parenthesized_ws(inner))


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
        pos = self.get_metadata(PositionProvider, original)
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
            pos = self.get_metadata(PositionProvider, node)
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
