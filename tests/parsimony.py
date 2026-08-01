"""
Tests for the parsimony line-breaker.
"""
from textwrap import dedent

import libcst as cst
from testsweet import params, test

import parsimony
from parsimony.brackets import _open_ws, _set_open_ws


def fmt(code):
    formatted, skipped = parsimony.format_code(code)
    return formatted


@test
def exploding_one_call_leaves_sibling_chained_calls_intact():
    # All calls in a left-leaning chain share a start position, so the
    # exploder must match the full span -- otherwise it also "explodes"
    # the trailing empty call into ``).build_result(\n)``.
    # ``configure`` is multi-arg, so exploding it fits the line; the
    # chain itself (configure + build) must be left intact.
    code = (
        'data = some_builder.configure('
        'option_one=1, option_two=2, option_three=3).build_result()\n'
    )
    expected = dedent("""\
        data = some_builder.configure(
            option_one=1,
            option_two=2,
            option_three=3,
        ).build_result()
    """)
    assert fmt(code) == expected


@test
class BreakingChains:
    BROKEN_CHAIN = dedent("""\
        django_queryset = (
            SomeModel
            .objects
            .filter(some_field='somevalue')
            .order_by('-some_other_field')
            .prefetch_related('related')
        )
    """)

    def breaks_long_method_chain(self):
        code = (
            'django_queryset = SomeModel.objects'
            ".filter(some_field='somevalue')"
            ".order_by('-some_other_field')"
            ".prefetch_related('related')\n"
        )
        assert fmt(code) == self.BROKEN_CHAIN

    def breaking_a_chain_is_idempotent(self):
        assert fmt(self.BROKEN_CHAIN) == self.BROKEN_CHAIN


@test
def chain_break_reindents_already_exploded_segment_args():
    # ``filter_gamma`` is multi-arg, so it explodes first. The prefix is
    # then still too long, forcing a chain break that shifts every
    # segment +4. Its already-exploded args must shift +4 too, or they
    # end up misaligned.
    code = (
        "queryset = base.filter_alpha('value').filter_beta('value')"
        ".filter_delta('value').filter_gamma(one='1', two='2')\n"
    )
    expected = dedent("""\
        queryset = (
            base
            .filter_alpha('value')
            .filter_beta('value')
            .filter_delta('value')
            .filter_gamma(
                one='1',
                two='2',
            )
        )
    """)
    assert fmt(code) == expected


@test
@params([
    (
        # No multi-item bracket, one call segment (not a chain)
        'result = some_object.some_method('
        'an_argument_that_is_really_quite_long_indeed_yes)\n',
    ),
    (
        # Bracket in f-string is left alone
        'string = f\'A bracket that looks like it should be exploded, but '
        'should not: {func(["one", "two", "three"])}\'\n',
    ),
    (
        # Chain in f-string is left alone
        'string = f\'A chain that looks breakable but is not: '
        '{obj.filter_one("a").filter_two("b").filter_three("c")}\'\n',
    ),
])
def overlong_but_unfixable_is_left_alone_and_reported(code):
    formatted, skipped = parsimony.format_code(code)
    assert formatted == code
    assert len(skipped) == 1


@test
class OpenWhitespaceAccess:
    # _open_ws and _set_open_ws replace two parallel isinstance ladders --
    # one that read the whitespace just inside the opening bracket and one
    # that wrote it -- with a single path table.
    MARKER = cst.ParenthesizedWhitespace(
        first_line=cst.TrailingWhitespace(newline=cst.Newline()),
        indent=False,
        last_line=cst.SimpleWhitespace('    '),
    )

    @params([
        ('f(a, b)',),
        ('[a, b]',),
        ('(a, b)',),
        ('{a, b}',),
        ("{'a': 1, 'b': 2}",),
        ('x[a, b]',),
    ])
    def round_trips_the_opening_whitespace(self, source):
        node = cst.parse_expression(source)
        assert _open_ws(node) is not None, source
        updated = _set_open_ws(node, self.MARKER)
        assert _open_ws(updated).deep_equals(self.MARKER), source

    def preserves_outer_parens_of_a_tuple(self):
        # Tuple.lpar is a sequence; only the innermost paren carries the
        # opening whitespace, and the rest must survive untouched.
        marker = cst.SimpleWhitespace('  ')
        node = cst.parse_expression('((a, b))')
        assert len(node.lpar) == 2
        updated = _set_open_ws(node, marker)
        assert len(updated.lpar) == 2
        assert updated.lpar[0].whitespace_after.deep_equals(marker)


@test
class NestedBreakDoesNotMaskAnOverlongHeader:
    # Testing the whole node for a newline could not tell "my own bracket is
    # open" from "some bracket nested inside me is open". So an unbroken but
    # over-long header was reported as already exploded, and left unfixed.
    CODE = (
        'result = some_function_with_a_longish_name('
        'alpha_value_here, beta_value_here, gamma, [\n'
        '    1111111,\n'
        '    2222222,\n'
        '])\n'
    )
    EXPECTED = (
        'result = some_function_with_a_longish_name(\n'
        '    alpha_value_here,\n'
        '    beta_value_here,\n'
        '    gamma,\n'
        '    [\n'
        '    1111111,\n'
        '    2222222,\n'
        '],\n'
        ')\n'
    )

    def explodes_the_outer_call(self):
        # The inner list stays where it was, misaligned. Re-indenting the
        # contents of an already-broken nested container is separate work.
        formatted, skipped = parsimony.format_code(self.CODE)
        assert formatted == self.EXPECTED
        assert skipped == []

    def the_result_is_idempotent(self):
        formatted, _skipped = parsimony.format_code(self.CODE)
        assert fmt(formatted) == formatted
