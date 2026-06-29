"""Breaking long method chains one segment per line."""
import libcst as cst
from libcst.metadata import ParentNodeProvider, PositionProvider

from parsimony.core import parenthesized_ws, span

# A method chain is only broken if it has at least this many call segments
# (``.method(...)`` links). A lone ``obj.method(args)`` is not a chain --
# its arguments are the bracket-exploder's job, not the chain-breaker's.
MIN_CHAIN_SEGMENTS = 2


def chain_info(node):
    """Walk a method chain's spine from its outermost node downward.

    Returns ``(dots, call_segments)`` where ``dots`` are the ``Attribute``
    dot nodes along the spine (the break points) and ``call_segments``
    counts the ``.method(...)`` links. The spine follows ``.func`` of each
    Call and ``.value`` of each Attribute; call arguments are off-spine and
    untouched.
    """
    dots = []
    call_segments = 0
    cur = node
    while True:
        if isinstance(cur, cst.Call):
            if isinstance(cur.func, cst.Attribute):
                call_segments += 1
            cur = cur.func
        elif isinstance(cur, cst.Attribute):
            dots.append(cur.dot)
            cur = cur.value
        else:
            break
    return dots, call_segments


def _chain_already_broken(dots):
    """True if any spine dot already carries a line break (idempotency)."""
    return any(
        isinstance(d.whitespace_before, cst.ParenthesizedWhitespace)
        for d in dots
    )


def _break_spine(node, inner):
    """Return ``node`` with a newline+indent before every spine dot."""
    if isinstance(node, cst.Call):
        return node.with_changes(func=_break_spine(node.func, inner))
    if isinstance(node, cst.Attribute):
        dot = node.dot.with_changes(whitespace_before=parenthesized_ws(inner))
        value = _break_spine(node.value, inner)
        return node.with_changes(dot=dot, value=value)
    return node


class _Reindenter(cst.CSTTransformer):
    """Shift every existing line break's hanging indent by `delta` spaces."""

    def __init__(self, delta):
        self.delta = delta

    def leave_ParenthesizedWhitespace(self, original_node, updated_node):
        last = updated_node.last_line
        return updated_node.with_changes(
            last_line=last.with_changes(value=last.value + ' ' * self.delta)
        )


def break_chain(node, inner, outer):
    """Return ``node`` with its chain split one-segment-per-line.

    The head stays on the opening line; each ``.attr`` is dedented onto its
    own ``+4`` line. The whole expression is wrapped in parentheses (reusing
    existing ones if already parenthesized) so the line breaks are legal.

    Breaking shifts every segment in by ``inner - outer`` (one INDENT), so
    any brackets the exploder already opened inside a segment are re-indented
    by the same amount to keep them aligned under their new, deeper segment.
    """
    delta = len(inner) - len(outer)
    node = node.visit(_Reindenter(delta))
    broken = _break_spine(node, inner)
    open_ws = parenthesized_ws(inner)
    close_ws = parenthesized_ws(outer)
    if broken.lpar:
        first_lpar = broken.lpar[0].with_changes(whitespace_after=open_ws)
        last_rpar = broken.rpar[-1].with_changes(whitespace_before=close_ws)
        lpar = [first_lpar, *broken.lpar[1:]]
        rpar = [*broken.rpar[:-1], last_rpar]
        return broken.with_changes(lpar=lpar, rpar=rpar)
    return broken.with_changes(
        lpar=[cst.LeftParen(whitespace_after=open_ws)],
        rpar=[cst.RightParen(whitespace_before=close_ws)],
    )


class ChainBreaker(cst.CSTTransformer):
    """Break the single chain whose full span matches `target`.

    Chain spine nodes share a start position (all left-leaning from the same
    head), so -- unlike the bracket exploder -- we match the full
    (start, end) span to pin the outermost node.
    """

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, target, inner, outer):
        self.target = target  # (start_line, start_col, end_line, end_col)
        self.inner = inner
        self.outer = outer

    def _maybe(self, original, updated):
        pos = self.get_metadata(PositionProvider, original)
        if span(pos) == self.target:
            return break_chain(updated, self.inner, self.outer)
        return updated

    def leave_Call(self, original_node, updated_node):
        return self._maybe(original_node, updated_node)

    def leave_Attribute(self, original_node, updated_node):
        return self._maybe(original_node, updated_node)


class ChainCollector(cst.CSTVisitor):
    """Collect outermost method chains with their position and break state."""

    METADATA_DEPENDENCIES = (PositionProvider, ParentNodeProvider)

    def __init__(self):
        self.found = []

    def on_visit(self, node):
        if isinstance(node, cst.FormattedString):
            # A chain inside an f-string is string content, not code:
            # breaking it would corrupt the literal. Don't descend.
            return False
        if isinstance(node, (cst.Call, cst.Attribute)):
            parent = self.get_metadata(ParentNodeProvider, node)
            in_spine = (
                (isinstance(parent, cst.Call) and parent.func is node)
                or (isinstance(parent, cst.Attribute) and parent.value is node)
            )
            if not in_spine:
                dots, segments = chain_info(node)
                if segments >= MIN_CHAIN_SEGMENTS:
                    pos = self.get_metadata(PositionProvider, node)
                    broken = _chain_already_broken(dots)
                    self.found.append({'pos': pos, 'broken': broken})
        return True
