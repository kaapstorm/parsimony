"""Exploding bracketed containers one element per line."""
import libcst as cst
from libcst.metadata import PositionProvider

from parsimony.core import parenthesized_ws, span

# Node types that carry an explodable comma-separated child list.
BRACKETED = (cst.Call, cst.List, cst.Tuple, cst.Set, cst.Dict, cst.Subscript)


def children_of(node):
    """Return the comma-separated children for a bracketed node."""
    if isinstance(node, cst.Call):
        return list(node.args)
    if isinstance(node, cst.Subscript):
        return list(node.slice)
    return list(node.elements)


def is_multi_item(node):
    return len(children_of(node)) >= 2


def is_explodable(node):
    """A bare tuple (`a, b` with no parens) has no bracket to open."""
    if isinstance(node, cst.Tuple):
        return bool(node.lpar)
    return True


def explode_bracket(node, inner, outer):
    """Return ``node`` with its children split one-per-line."""
    kids = children_of(node)
    new_kids = []
    for i, kid in enumerate(kids):
        last = i == len(kids) - 1
        whitespace_after = parenthesized_ws(outer if last else inner)
        comma = cst.Comma(whitespace_after=whitespace_after)
        new_kids.append(kid.with_changes(comma=comma))

    open_ws = parenthesized_ws(inner)
    if isinstance(node, cst.Call):
        return node.with_changes(whitespace_before_args=open_ws, args=new_kids)
    if isinstance(node, cst.Subscript):
        lbracket = node.lbracket.with_changes(whitespace_after=open_ws)
        return node.with_changes(lbracket=lbracket, slice=new_kids)
    if isinstance(node, cst.List):
        lbracket = node.lbracket.with_changes(whitespace_after=open_ws)
        return node.with_changes(lbracket=lbracket, elements=new_kids)
    if isinstance(node, (cst.Set, cst.Dict)):
        lbrace = node.lbrace.with_changes(whitespace_after=open_ws)
        return node.with_changes(lbrace=lbrace, elements=new_kids)
    assert isinstance(node, cst.Tuple)
    lpar = [
        node.lpar[0].with_changes(whitespace_after=open_ws),
        *node.lpar[1:],
    ]
    return node.with_changes(lpar=lpar, elements=new_kids)


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
        if isinstance(node, BRACKETED):
            pos = self.get_metadata(PositionProvider, node)
            already = '\n' in cst.Module([]).code_for_node(node)
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
