"""
Tests for the parsimony line-breaker.
"""
from textwrap import dedent

import libcst as cst
from testsweet import params, test

import parsimony
from parsimony.brackets import (
    _open_ws,
    _set_open_ws,
    _slot_container,
    flatten_slots,
    unflatten_slots,
)


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
class ExplodingDefParams:
    HEADLINE = dedent("""\
        def some_method(
            self,
            param1: str,
            param2: int,
            param3: bool | None = None,
            *args,
            **kwargs,
        ):
            ...
    """)

    def explodes_long_def_params(self):
        code = (
            'def some_method(self, param1: str, param2: int, '
            'param3: bool | None = None, *args, **kwargs):\n'
            '    ...\n'
        )
        assert fmt(code) == self.HEADLINE

    def exploding_def_params_is_idempotent(self):
        assert fmt(self.HEADLINE) == self.HEADLINE

    def explodes_async_def_params(self):
        code = (
            'async def handle(self, request_argument, response_argument, '
            'extra_context_argument):\n'
            '    ...\n'
        )
        expected = dedent("""\
            async def handle(
                self,
                request_argument,
                response_argument,
                extra_context_argument,
            ):
                ...
        """)
        assert fmt(code) == expected

    def preserves_slash_and_star_separators(self):
        code = (
            'def fancy(alpha_value, beta_value, /, gamma_value, *, '
            'delta_value, epsilon_value):\n'
            '    ...\n'
        )
        expected = dedent("""\
            def fancy(
                alpha_value,
                beta_value,
                /,
                gamma_value,
                *,
                delta_value,
                epsilon_value,
            ):
                ...
        """)
        assert fmt(code) == expected

    def explodes_param_list_before_inner_default(self):
        # The line is long because of the param list; the param list is the
        # shallowest container, so it is exploded first and the inner default
        # dict (now fitting) is left alone.
        code = (
            'def configure(first_option, second_option, '
            "third_option={'a': 1, 'b': 2, 'c': 3, 'd': 4}):\n"
            '    ...\n'
        )
        expected = dedent("""\
            def configure(
                first_option,
                second_option,
                third_option={'a': 1, 'b': 2, 'c': 3, 'd': 4},
            ):
                ...
        """)
        assert fmt(code) == expected

    def explodes_def_with_multiline_default(self):
        # The first physical line is 80 chars (over the 79 limit). The param
        # list is a 3-item container that must explode. The pre-existing
        # multi-line default carries an inner newline that must NOT fool
        # _already_exploded into treating the params as already broken.
        code = (
            'def configure(first_option_argument_long, '
            'second_option_argument_xx, third_opt={\n'
            "    'a': 1,\n"
            "    'b': 2,\n"
            '}):\n'
            '    ...\n'
        )
        result = fmt(code)
        assert result != code  # the over-long line was fixed
        assert fmt(result) == result  # idempotent
        assert result == (
            'def configure(\n'
            '    first_option_argument_long,\n'
            '    second_option_argument_xx,\n'
            '    third_opt={\n'
            "    'a': 1,\n"
            "    'b': 2,\n"
            '},\n'
            '):\n'
            '    ...\n'
        )


@test
class ExplodingClassBases:
    BASES = dedent("""\
        class MyView(
            LoginRequiredMixin,
            GenericDetailView,
            ExtraMixinForGoodMeasure,
            metaclass=MetaThing,
        ):
            pass
    """)

    def explodes_long_class_bases(self):
        code = (
            'class MyView(LoginRequiredMixin, GenericDetailView, '
            'ExtraMixinForGoodMeasure, metaclass=MetaThing):\n'
            '    pass\n'
        )
        assert fmt(code) == self.BASES

    def exploding_class_bases_is_idempotent(self):
        assert fmt(self.BASES) == self.BASES

    def explodes_keyword_only_class(self):
        # A class with ONLY keyword arguments and no positional bases
        # exercises an empty leading slot in the _SLOTS entry for ClassDef.
        code = (
            'class Foo(metaclass=SomeLongMetaclassName, '
            'another_keyword=SomeLongValue, yet_another=AnotherLongValue):\n'
            '    pass\n'
        )
        result = fmt(code)
        assert result != code  # the over-long line was fixed
        assert fmt(result) == result  # idempotent
        assert result == dedent("""\
            class Foo(
                metaclass=SomeLongMetaclassName,
                another_keyword=SomeLongValue,
                yet_another=AnotherLongValue,
            ):
                pass
        """)


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
    (
        # Single-parameter def: nothing to explode (multi-item gate)
        'def function_that_does_something('
        'only_one_really_quite_long_single_parameter_name_here):\n'
        '    ...\n',
    ),
    (
        # Single-base class with a long name: one item, not multi
        'class FooBarBazQuux('
        'AnExceedinglyLongAndVeryDescriptiveSingleBaseClassNameHereOkayYes):\n'
        '    pass\n',
    ),
])
def overlong_but_unfixable_is_left_alone_and_reported(code):
    formatted, skipped = parsimony.format_code(code)
    assert formatted == code
    assert len(skipped) == 1


@test
class SlotRoundTrip:
    # Flattening a slot container and immediately rebuilding it must be a
    # no-op for every slot layout. This is the guard that the flatten and
    # rebuild halves cannot drift apart: they read one description in
    # _SLOTS instead of mirroring each other by hand.
    #
    # libcst only catches *some* drift. Misplacing a ParamSlash raises, but
    # the posonly_params/params boundary is silent -- posonly_ind defaults to
    # MaybeSentinel.DEFAULT, which renders a `/` whenever posonly_params is
    # non-empty, so `def f(a, b, c)` can silently become `def f(a, /, b, c)`.
    @params([
        ('def f(): pass',),
        ('def f(a, b): pass',),
        ('def f(a, /, b): pass',),
        ('def f(a, *args): pass',),
        ('def f(a, *, b): pass',),
        ('def f(a, **kwargs): pass',),
        ('def f(a, /, b, *args, c, **kwargs): pass',),
    ])
    def flatten_then_unflatten_is_a_no_op(self, source):
        container = _slot_container(cst.parse_module(source).body[0])
        children, plan = flatten_slots(container)
        rebuilt = unflatten_slots(container, plan, children)
        assert rebuilt.deep_equals(container), source

    def flatten_returns_children_in_source_order(self):
        source = 'def f(a, /, b, *args, c, **kwargs): pass'
        container = _slot_container(cst.parse_module(source).body[0])
        children, _plan = flatten_slots(container)
        rendered = [
            cst.Module([]).code_for_node(child).strip().rstrip(',')
            for child in children
        ]
        assert rendered == ['a', '/', 'b', '*args', 'c', '**kwargs']


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

    @params([
        ('def f(a, b): pass',),
        ('class C(A, B): pass',),
    ])
    def round_trips_for_def_and_class(self, source):
        node = cst.parse_module(source).body[0]
        updated = _set_open_ws(node, self.MARKER)
        assert _open_ws(updated).deep_equals(self.MARKER), source

    def returns_none_when_there_is_no_bracket(self):
        # A bare tuple has lpar == (); a paren-less class has
        # lpar == MaybeSentinel.DEFAULT. BracketCollector asks about both,
        # so walking the path must not be attempted for either.
        bare_tuple = cst.parse_expression('1, 2')
        assert isinstance(bare_tuple, cst.Tuple) and not bare_tuple.lpar
        assert _open_ws(bare_tuple) is None

        bare_class = cst.parse_module('class C: pass').body[0]
        assert _open_ws(bare_class) is None

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
    # _already_exploded used a whole-node newline test for the six literal
    # bracket types, which could not tell "my own bracket is open" from
    # "some bracket nested inside me is open". So an unbroken but over-long
    # header was reported as already exploded, and left unfixed.
    #
    # The def/class branches never had this bug: their check was already
    # scoped to the header. Generalising it removes the bug and the special
    # case together.
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
        # The inner list stays where it was, misaligned. That matches the
        # existing behaviour for a def with a multi-line default -- see
        # ExplodingDefParams.explodes_def_with_multiline_default -- and is
        # out of scope here.
        #
        # This expectation is pinned, not endorsed: re-indenting the
        # contents of an already-broken nested container is the next piece
        # of work, and it will rewrite this string and that one.
        formatted, skipped = parsimony.format_code(self.CODE)
        assert formatted == self.EXPECTED
        assert skipped == []

    def the_result_is_idempotent(self):
        formatted, _skipped = parsimony.format_code(self.CODE)
        assert fmt(formatted) == formatted
