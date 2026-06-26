"""
Tests for the parsimony line-breaker.
"""
from textwrap import dedent
from testsweet import test

import parsimony


def fmt(code):
    formatted, skipped = parsimony.format_code(code)
    return formatted


@test
def exploding_one_call_leaves_sibling_chained_calls_intact():
    # All calls in a left-leaning chain share a start position, so the
    # exploder must match the full span -- otherwise it also "explodes"
    # the trailing empty call into ``).build_result(\n)``.
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
def breaks_long_method_chain():
    code = (
        'django_queryset = SomeModel.objects'
        ".filter(some_field='somevalue')"
        ".order_by('-some_other_field')"
        ".prefetch_related('related')\n"
    )
    expected = dedent("""\
        django_queryset = (
            SomeModel
            .objects
            .filter(some_field='somevalue')
            .order_by('-some_other_field')
            .prefetch_related('related')
        )
    """)
    assert fmt(code) == expected


@test
def breaking_a_chain_is_idempotent():
    already_broken = dedent("""\
        django_queryset = (
            SomeModel
            .objects
            .filter(some_field='somevalue')
            .order_by('-some_other_field')
            .prefetch_related('related')
        )
    """)
    assert fmt(already_broken) == already_broken


@test
def prefers_exploding_a_bracket_over_breaking_the_chain():
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
def short_chain_is_left_alone_and_reported():
    # One call segment -- not a chain. No multi-item bracket either, so
    # there is nothing to break; report it instead.
    code = (
        'result = some_object.some_method('
        'an_argument_that_is_really_quite_long_indeed_yes)\n'
    )
    formatted, skipped = parsimony.format_code(code)
    assert formatted == code
    assert len(skipped) == 1
