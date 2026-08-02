"""Shared primitives used by the bracket and chain transformers."""
import libcst as cst

LINE_LENGTH = 79
INDENT = 4


def parenthesized_ws(indent):
    return cst.ParenthesizedWhitespace(
        first_line=cst.TrailingWhitespace(newline=cst.Newline()),
        indent=False,
        last_line=cst.SimpleWhitespace(indent),
    )


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
