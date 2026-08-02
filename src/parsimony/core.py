"""Shared primitives used by the bracket and chain transformers."""
import libcst as cst
from libcst.metadata import PositionProvider

LINE_LENGTH = 79
INDENT = 4


def parenthesized_ws(indent):
    return cst.ParenthesizedWhitespace(
        first_line=cst.TrailingWhitespace(newline=cst.Newline()),
        indent=False,
        last_line=cst.SimpleWhitespace(indent),
    )


def rehung_ws(existing, indent):
    """The whitespace for a break hanging at ``indent``.

    Reuses ``existing`` when it already spans lines, rewriting only its
    hanging indent, so that a comment parked beside a reused paren --
    ``if (  # explain the check`` -- survives instead of being silently
    deleted. ``indent`` is forced off libcst's own indent tracking so
    the value we compute is the value emitted.

    A ``SimpleWhitespace`` cannot hold a comment or a line break, so
    there is nothing to preserve and a fresh break is used.
    """
    if isinstance(existing, cst.ParenthesizedWhitespace):
        return existing.with_changes(
            indent=False, last_line=cst.SimpleWhitespace(indent)
        )
    return parenthesized_ws(indent)


def break_in_parens(node, break_spine, inner, outer, delta=None):
    """Return ``node`` with its spine broken, wrapped in parentheses.

    ``break_spine(node, inner)`` is the strategy's own walk -- boolean
    operators for a condition, dots for a chain. Everything around it is
    common: reindent, then parenthesize so the new breaks are legal,
    reusing the author's parens rather than doubling them.

    ``delta`` is how far the spine moves: existing breaks inside ``node``
    shift by the same amount to stay aligned under their new position.
    It defaults to one level, which is right whenever the expression
    currently starts on the line the parens do. An expression already
    parenthesized ACROSS lines does not move at all, so its caller passes
    a delta of its own.
    """
    if delta is None:
        delta = len(inner) - len(outer)
    broken = break_spine(node.visit(Reindenter(delta)), inner)
    if broken.lpar:
        first_lpar = broken.lpar[0]
        last_rpar = broken.rpar[-1]
        return broken.with_changes(
            lpar=[
                first_lpar.with_changes(
                    whitespace_after=rehung_ws(
                        first_lpar.whitespace_after, inner
                    )
                ),
                *broken.lpar[1:],
            ],
            rpar=[
                *broken.rpar[:-1],
                last_rpar.with_changes(
                    whitespace_before=rehung_ws(
                        last_rpar.whitespace_before, outer
                    )
                ),
            ],
        )
    return broken.with_changes(
        lpar=[cst.LeftParen(whitespace_after=parenthesized_ws(inner))],
        rpar=[cst.RightParen(whitespace_before=parenthesized_ws(outer))],
    )


def paren_line(get_metadata, node):
    """The line whose indent is the base for breaking ``node``.

    PositionProvider EXCLUDES an expression's own parentheses. For one
    the author already parenthesized ACROSS lines, the node's own start
    is therefore the continuation line -- one level too deep -- and
    breaking from it would push the operands deeper still and leave the
    closing paren at the body's indent. The opening paren's line is the
    statement line, which is the indent the closing paren returns to.
    """
    if node.lpar:
        return get_metadata(PositionProvider, node.lpar[0]).start.line
    return get_metadata(PositionProvider, node).start.line


def overlong_lines(code):
    return {
        i for i, line in enumerate(code.splitlines(), 1)
        if len(line) > LINE_LENGTH
    }


def line_indent(code, lineno):
    line = code.splitlines()[lineno - 1]
    return len(line) - len(line.lstrip())


def span(pos):
    """The (start_line, start_col, end_line, end_col) of a node's position."""
    return pos.start.line, pos.start.column, pos.end.line, pos.end.column


class Reindenter(cst.CSTTransformer):
    """Shift every existing line break's hanging indent by `delta` spaces.

    Used by every strategy that adds a level of indentation to code that
    already contains line breaks: wrapping an expression in parentheses, or
    exploding a container around an already-broken child. Relative indents
    inside the node are preserved, because every break shifts equally.
    """

    def __init__(self, delta):
        self.delta = delta

    def leave_ParenthesizedWhitespace(self, original_node, updated_node):
        last = updated_node.last_line
        return updated_node.with_changes(
            last_line=last.with_changes(value=last.value + ' ' * self.delta)
        )
