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
