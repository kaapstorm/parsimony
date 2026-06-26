"""The line-breaking driver: explode brackets, then break chains."""
import libcst as cst
from libcst.metadata import MetadataWrapper

from parsimony.brackets import BracketCollector, BracketExploder
from parsimony.chains import ChainBreaker, ChainCollector
from parsimony.core import INDENT, line_indent, overlong_lines, span


def format_code(code):
    """Return (formatted_code, skipped) where skipped lists (lineno, text)
    of lines still over the limit that no bracket rule could fix."""
    for _ in range(50):  # safety cap
        bad = overlong_lines(code)
        if not bad:
            return code, []

        wrapper = MetadataWrapper(cst.parse_module(code))
        collector = BracketCollector()
        wrapper.visit(collector)

        # Candidates: not-yet-exploded MULTI-ITEM containers intersecting an
        # over-long line. We deliberately ignore single-item containers --
        # hanging a lone element is the staircase ugliness we avoid, and it is
        # never safe for a subscript index (`x[0]` -> `x[0,]` changes meaning).
        candidates = [
            c
            for c in collector.found
            if not c['exploded']
            and c['explodable']
            and c['multi']
            and bad & set(range(c['pos'].start.line, c['pos'].end.line + 1))
        ]
        if candidates:
            # Priority: outermost (shallowest) container.
            chosen = max(candidates, key=lambda c: -c['depth'])
            pos = chosen['pos']
            outer = line_indent(code, pos.start.line)
            inner = outer + INDENT

            wrapper = MetadataWrapper(cst.parse_module(code))
            exploder = BracketExploder(span(pos), ' ' * inner, ' ' * outer)
            code = wrapper.visit(exploder).code
            continue

        # Fallback: no bracket can fix the remaining long lines. Break the
        # outermost unbroken method chain that intersects one of them.
        wrapper = MetadataWrapper(cst.parse_module(code))
        chains = ChainCollector()
        wrapper.visit(chains)
        chain_candidates = [
            c
            for c in chains.found
            if not c['broken']
            and bad & set(range(c['pos'].start.line, c['pos'].end.line + 1))
        ]
        if not chain_candidates:
            break  # nothing left we know how to break

        chosen = min(
            chain_candidates,
            key=lambda c: (c['pos'].start.line, c['pos'].start.column),
        )
        pos = chosen['pos']
        outer = line_indent(code, pos.start.line)
        inner = outer + INDENT

        wrapper = MetadataWrapper(cst.parse_module(code))
        breaker = ChainBreaker(span(pos), ' ' * inner, ' ' * outer)
        code = wrapper.visit(breaker).code

    lines = code.splitlines()
    skipped = [(i, lines[i - 1]) for i in sorted(overlong_lines(code))]
    return code, skipped
