"""Breaking long boolean conditions one operand per line."""
import libcst as cst

from parsimony.core import Reindenter, parenthesized_ws

# Statements whose header is a condition we know how to break. Both span
# their body, but their ``.test`` does not -- so, unlike def/class, the
# test's own span is already the header-only region we need.
CONDITIONAL = (cst.If, cst.While)


def spine_operators(node):
    """Yield a condition's boolean operators, in source order.

    Recurses into both sides. Unlike a method chain, a boolean spine is
    not purely left-leaning: ``a or b and c`` puts the higher-precedence
    ``and`` on the right, so a left-only walk would miss it.

    The recursion stops at any operand the author parenthesised: that is
    a deliberate grouping, and it stays on one line as a single operand.
    The cutoff deliberately does not apply to ``node`` itself, so an
    already-parenthesised test (``if (a and b):``) is still breakable.
    """
    if not isinstance(node, cst.BooleanOperation):
        return
    yield from _operand_operators(node.left)
    yield node.operator
    yield from _operand_operators(node.right)


def _operand_operators(node):
    """``spine_operators`` for an operand: nothing if it has its own parens."""
    if isinstance(node, cst.BooleanOperation) and not node.lpar:
        yield from spine_operators(node)


def _condition_already_broken(node):
    """True if any spine operator already carries a line break."""
    return any(
        isinstance(op.whitespace_before, cst.ParenthesizedWhitespace)
        for op in spine_operators(node)
    )


def _break_spine(node, inner):
    """Return ``node`` with a newline+indent before every spine operator."""
    operator = node.operator.with_changes(
        whitespace_before=parenthesized_ws(inner)
    )
    return node.with_changes(
        left=_break_operand(node.left, inner),
        operator=operator,
        right=_break_operand(node.right, inner),
    )


def _break_operand(node, inner):
    """``_break_spine`` for an operand: untouched if it has its own parens."""
    if isinstance(node, cst.BooleanOperation) and not node.lpar:
        return _break_spine(node, inner)
    return node


def break_condition(node, inner, outer):
    """Return the boolean expression ``node`` split one operand per line.

    Every operand goes on its own ``+4`` line -- each but the first led by
    its operator -- and the closing paren is dedented to the opening
    line's indent. The expression is wrapped in parentheses (reusing
    existing ones if already parenthesized) so the breaks are legal.

    Breaking shifts every operand in by ``inner - outer`` (one INDENT), so
    any brackets the exploder already opened inside the condition are
    re-indented by the same amount.
    """
    delta = len(inner) - len(outer)
    node = node.visit(Reindenter(delta))
    broken = _break_spine(node, inner)
    open_ws = parenthesized_ws(inner)
    close_ws = parenthesized_ws(outer)
    if broken.lpar:
        first_lpar = broken.lpar[0].with_changes(whitespace_after=open_ws)
        last_rpar = broken.rpar[-1].with_changes(whitespace_before=close_ws)
        return broken.with_changes(
            lpar=[first_lpar, *broken.lpar[1:]],
            rpar=[*broken.rpar[:-1], last_rpar],
        )
    return broken.with_changes(
        lpar=[cst.LeftParen(whitespace_after=open_ws)],
        rpar=[cst.RightParen(whitespace_before=close_ws)],
    )
