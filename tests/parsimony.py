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
from parsimony.conditions import (
    _condition_already_broken,
    break_condition,
    spine_operators,
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
        assert result == dedent("""\
            def configure(
                first_option_argument_long,
                second_option_argument_xx,
                third_opt={
                    'a': 1,
                    'b': 2,
                },
            ):
                ...
        """)


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
class ExplodingAHeaderLeavesTheBodyAlone:
    # A def/class node spans its whole body, so a reindent applied to the
    # node -- rather than to its children -- shifts every pre-existing
    # break in the body by +4. That corrupts code Parsimony must never
    # touch, and it is idempotent, so a re-run does not repair it.

    def a_def_body_is_not_reindented(self):
        code = (
            'def some_function_name(alpha_parameter, beta_parameter, '
            'gamma_parameter, delta):\n'
            '    result = compute(\n'
            '        first_argument,\n'
            '        second_argument,\n'
            '    )\n'
            '    return result\n'
        )
        expected = dedent("""\
            def some_function_name(
                alpha_parameter,
                beta_parameter,
                gamma_parameter,
                delta,
            ):
                result = compute(
                    first_argument,
                    second_argument,
                )
                return result
        """)
        assert fmt(code) == expected
        assert fmt(expected) == expected  # idempotent

    def a_class_body_is_not_reindented(self):
        code = (
            'class MyView(LoginRequiredMixin, GenericDetailView, '
            'ExtraMixinForGoodMeasureXyz):\n'
            '    attribute = compute(\n'
            '        first_argument,\n'
            '        second_argument,\n'
            '    )\n'
        )
        expected = dedent("""\
            class MyView(
                LoginRequiredMixin,
                GenericDetailView,
                ExtraMixinForGoodMeasureXyz,
            ):
                attribute = compute(
                    first_argument,
                    second_argument,
                )
        """)
        assert fmt(code) == expected
        assert fmt(expected) == expected  # idempotent


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
    EXPECTED = dedent("""\
        result = some_function_with_a_longish_name(
            alpha_value_here,
            beta_value_here,
            gamma,
            [
                1111111,
                2222222,
            ],
        )
    """)

    def explodes_the_outer_call(self):
        # Exploding the call shifts every child in by one INDENT, so the
        # list's own already-broken contents shift with it and stay
        # aligned under their new position. This is the same reindent
        # break_chain does when wrapping shifts a chain deeper.
        formatted, skipped = parsimony.format_code(self.CODE)
        assert formatted == self.EXPECTED
        assert skipped == []

    def the_result_is_idempotent(self):
        formatted, _skipped = parsimony.format_code(self.CODE)
        assert fmt(formatted) == formatted


@test
def explode_reindents_a_child_starting_on_a_later_line():
    # The second list starts on line 3, not on the container's opening
    # line, so it is the case a single container-wide delta might get
    # wrong. It does not: Parsimony dedents a closing bracket to its own
    # opening line's indent, so a following sibling resumes at `outer`
    # and shifts by the same one INDENT as the rest.
    code = (
        'result = some_function_with_a_really_quite_long_name_here('
        'alpha_value_here_xyz, [\n'
        '    1111111,\n'
        '], [\n'
        '    2222222,\n'
        '])\n'
    )
    expected = dedent("""\
        result = some_function_with_a_really_quite_long_name_here(
            alpha_value_here_xyz,
            [
                1111111,
            ],
            [
                2222222,
            ],
        )
    """)
    assert fmt(code) == expected
    assert fmt(expected) == expected  # idempotent


@test
class ConditionSpines:
    def flattens_every_joint_across_precedence(self):
        # `a and b or c and d` parses as `(a and b) or (c and d)`, so the
        # higher-precedence `and`s sit on both sides of the `or`. A
        # left-only walk -- what chain_info does -- would find only two.
        node = cst.parse_expression('alpha and beta or gamma and delta')
        assert len(list(spine_operators(node))) == 3

    def stops_at_an_author_parenthesized_operand(self):
        node = cst.parse_expression('alpha and (beta or gamma)')
        assert len(list(spine_operators(node))) == 1

    def enters_a_parenthesized_root(self):
        # The lpar cutoff applies to operands, not to the node the
        # breaker was handed: `if (a and b):` must still be breakable.
        node = cst.parse_expression('(alpha and beta)')
        assert len(list(spine_operators(node))) == 1

    def yields_nothing_for_a_non_boolean_expression(self):
        node = cst.parse_expression('alpha == beta')
        assert list(spine_operators(node)) == []

    def an_unbroken_condition_is_not_already_broken(self):
        node = cst.parse_expression('alpha and beta')
        assert not _condition_already_broken(node)

    def a_broken_condition_is_detected(self):
        node = break_condition(
            cst.parse_expression('alpha and beta'), '    ', ''
        )
        assert _condition_already_broken(node)

    def break_condition_renders_one_operand_per_line(self):
        node = cst.parse_expression('alpha and beta or gamma')
        rendered = cst.Module([]).code_for_node(
            break_condition(node, '    ', '')
        )
        assert rendered == dedent("""\
            (
                alpha
                and beta
                or gamma
            )""")

    def break_condition_reuses_existing_parens(self):
        node = cst.parse_expression('(alpha and beta)')
        rendered = cst.Module([]).code_for_node(
            break_condition(node, '    ', '')
        )
        assert rendered == dedent("""\
            (
                alpha
                and beta
            )""")


@test
class BreakingConditions:
    BROKEN = dedent("""\
        if (
            some_condition_value
            and another_condition_value
            and a_third_condition_value
        ):
            pass
    """)

    def breaks_a_long_if_condition(self):
        code = (
            'if some_condition_value and another_condition_value'
            ' and a_third_condition_value:\n'
            '    pass\n'
        )
        assert fmt(code) == self.BROKEN

    def breaking_a_condition_is_idempotent(self):
        assert fmt(self.BROKEN) == self.BROKEN

    def breaks_an_elif_condition(self):
        code = (
            'if x:\n'
            '    pass\n'
            'elif some_condition_value and another_condition_value'
            ' and a_third_condition_val:\n'
            '    pass\n'
        )
        assert fmt(code) == dedent("""\
            if x:
                pass
            elif (
                some_condition_value
                and another_condition_value
                and a_third_condition_val
            ):
                pass
        """)

    def breaks_a_while_condition(self):
        code = (
            'while some_condition_value and another_condition_value'
            ' and a_third_condition_val:\n'
            '    pass\n'
        )
        assert fmt(code) == dedent("""\
            while (
                some_condition_value
                and another_condition_value
                and a_third_condition_val
            ):
                pass
        """)

    def breaks_at_the_conditions_own_indent(self):
        code = (
            'def f():\n'
            '    if some_condition_value and another_condition_value'
            ' and a_third_condition_v:\n'
            '        pass\n'
        )
        assert fmt(code) == dedent("""\
            def f():
                if (
                    some_condition_value
                    and another_condition_value
                    and a_third_condition_v
                ):
                    pass
        """)

    def flattens_every_joint_regardless_of_precedence(self):
        code = (
            'if alpha_value_here and beta_value_here or gamma_value_here'
            ' and delta_value_heree:\n'
            '    pass\n'
        )
        assert fmt(code) == dedent("""\
            if (
                alpha_value_here
                and beta_value_here
                or gamma_value_here
                and delta_value_heree
            ):
                pass
        """)

    def keeps_an_author_parenthesized_operand_on_one_line(self):
        code = (
            'if alpha_value_here and (beta_value_here or gamma_value_here)'
            ' and delta_value_xyz:\n'
            '    pass\n'
        )
        assert fmt(code) == dedent("""\
            if (
                alpha_value_here
                and (beta_value_here or gamma_value_here)
                and delta_value_xyz
            ):
                pass
        """)

    def reuses_an_already_parenthesized_test(self):
        code = (
            'if (some_condition_value and another_condition_value'
            ' and a_third_condition_xyzz):\n'
            '    pass\n'
        )
        assert fmt(code) == dedent("""\
            if (
                some_condition_value
                and another_condition_value
                and a_third_condition_xyzz
            ):
                pass
        """)


@test
def condition_break_reindents_an_already_exploded_call():
    # `check_one` is multi-arg, so it explodes first. The tail is still
    # too long, forcing a condition break that shifts everything +4. The
    # call's already-exploded args must shift +4 too, or they end up
    # misaligned. This is the analogue of
    # chain_break_reindents_already_exploded_segment_args.
    code = (
        'if check_one(alpha_value_here, beta_value_here)'
        ' and some_quite_long_condition_name_here'
        ' and another_condition_name_goes_right_here:\n'
        '    pass\n'
    )
    expected = dedent("""\
        if (
            check_one(
                alpha_value_here,
                beta_value_here,
            )
            and some_quite_long_condition_name_here
            and another_condition_name_goes_right_here
        ):
            pass
    """)
    assert fmt(code) == expected
    assert fmt(expected) == expected  # idempotent


@test
class BreakingAnAlreadyParenthesizedExpression:
    # PositionProvider EXCLUDES an expression's own parentheses, so for
    # one the author already spread across lines, the node's start is the
    # CONTINUATION line. Taking the indent from there put the operands a
    # level too deep and the closing paren at the body's indent.

    def a_condition_breaks_at_the_statement_indent(self):
        code = (
            'if (\n'
            '    some_condition_value_here and another_condition_values'
            ' and a_third_cond_valu\n'
            '):\n'
            '    pass\n'
        )
        expected = dedent("""\
            if (
                some_condition_value_here
                and another_condition_values
                and a_third_cond_valu
            ):
                pass
        """)
        assert fmt(code) == expected
        assert fmt(expected) == expected  # idempotent

    def a_chain_breaks_at_the_statement_indent(self):
        code = (
            'x = (\n'
            "    SomeModel.objects.filter_alpha('value').order_by('bbbb')"
            ".prefetch('related')\n"
            ')\n'
        )
        expected = dedent("""\
            x = (
                SomeModel
                .objects
                .filter_alpha('value')
                .order_by('bbbb')
                .prefetch('related')
            )
        """)
        assert fmt(code) == expected
        assert fmt(expected) == expected  # idempotent

    def an_already_exploded_call_inside_does_not_move(self):
        # The operands stay on the line they are already on, so -- unlike
        # the flat case -- nothing inside them shifts. A blanket +4
        # reindent would misalign the exploded call's arguments.
        code = (
            'if (\n'
            '    check_one(\n'
            '        alpha_value_here,\n'
            '        beta_value_here,\n'
            '    ) and some_quite_long_condition_name'
            ' and another_condition_names_here_xyzabc\n'
            '):\n'
            '    pass\n'
        )
        expected = dedent("""\
            if (
                check_one(
                    alpha_value_here,
                    beta_value_here,
                )
                and some_quite_long_condition_name
                and another_condition_names_here_xyzabc
            ):
                pass
        """)
        assert fmt(code) == expected
        assert fmt(expected) == expected  # idempotent


@test
class CommentsBesideReusedParens:
    # Overwriting a reused paren's whitespace wholesale destroys any
    # comment living there. Silent data loss is not an acceptable
    # outcome -- declining to format would be, but here we can keep it.

    def a_condition_keeps_an_opening_comment(self):
        code = (
            'if (  # explain the check\n'
            '    some_condition_value_here and another_condition_values'
            ' and a_third_cond_valu\n'
            '):\n'
            '    pass\n'
        )
        expected = dedent("""\
            if (  # explain the check
                some_condition_value_here
                and another_condition_values
                and a_third_cond_valu
            ):
                pass
        """)
        assert fmt(code) == expected
        assert fmt(expected) == expected  # idempotent

    def a_chain_keeps_an_opening_comment(self):
        code = (
            'x = (  # explain the chain\n'
            "    SomeModel.objects.filter_alpha('value').order_by('bbbb')"
            ".prefetch('related')\n"
            ')\n'
        )
        expected = dedent("""\
            x = (  # explain the chain
                SomeModel
                .objects
                .filter_alpha('value')
                .order_by('bbbb')
                .prefetch('related')
            )
        """)
        assert fmt(code) == expected
        assert fmt(expected) == expected  # idempotent

    def a_condition_keeps_a_closing_comment(self):
        code = (
            'if (\n'
            '    some_condition_value_here and another_condition_values'
            ' and a_third_cond_valu\n'
            '    # a closing note\n'
            '):\n'
            '    pass\n'
        )
        expected = dedent("""\
            if (
                some_condition_value_here
                and another_condition_values
                and a_third_cond_valu
                # a closing note
            ):
                pass
        """)
        assert fmt(code) == expected
        assert fmt(expected) == expected  # idempotent

    def a_chain_keeps_a_closing_comment(self):
        code = (
            'x = (\n'
            "    SomeModel.objects.filter_alpha('value').order_by('bbbb')"
            ".prefetch('related')\n"
            '    # a closing note\n'
            ')\n'
        )
        expected = dedent("""\
            x = (
                SomeModel
                .objects
                .filter_alpha('value')
                .order_by('bbbb')
                .prefetch('related')
                # a closing note
            )
        """)
        assert fmt(code) == expected
        assert fmt(expected) == expected  # idempotent

    def an_indented_opening_comment_keeps_its_body_indent(self):
        # A reused ParenthesizedWhitespace carries libcst's own indent
        # tracking, which would be applied ON TOP of the indent we
        # compute. Nested one level in, that would double it.
        code = (
            'def f():\n'
            '    if (  # explain\n'
            '        some_condition_value_here and another_condition_val'
            ' and a_third_cond_val\n'
            '    ):\n'
            '        pass\n'
        )
        expected = dedent("""\
            def f():
                if (  # explain
                    some_condition_value_here
                    and another_condition_val
                    and a_third_cond_val
                ):
                    pass
        """)
        assert fmt(code) == expected
        assert fmt(expected) == expected  # idempotent


@test
def a_bracket_that_fixes_the_line_is_preferred_over_the_condition():
    # Bracket explosion comes first in the strategy order, so a call that
    # can be opened is opened and the condition is left alone.
    code = (
        'if some_function_call(alpha_value, beta_value, gamma_value,'
        ' delta_value) and flagg:\n'
        '    pass\n'
    )
    assert fmt(code) == dedent("""\
        if some_function_call(
            alpha_value,
            beta_value,
            gamma_value,
            delta_value,
        ) and flagg:
            pass
    """)


@test
def a_condition_is_broken_in_preference_to_a_chain_inside_it():
    # Conditions come before chains in the strategy order, and breaking
    # the condition is enough, so the chain stays on one line.
    code = (
        'if base.filter_alpha().filter_beta().filter_gamma().filter_delta()'
        ' and other_flagg:\n'
        '    pass\n'
    )
    assert fmt(code) == dedent("""\
        if (
            base.filter_alpha().filter_beta().filter_gamma().filter_delta()
            and other_flagg
        ):
            pass
    """)


@test
class ConditionsLeftAlone:
    # Each of these is an over-long condition the breaker deliberately
    # does not touch. They are pinned so the boundary is enforced rather
    # than assumed -- if one starts being fixed, that should be a
    # decision, not a surprise.

    def a_negated_condition_is_reported_not_broken(self):
        # `not (...)` makes the test a UnaryOperation, so there is no
        # candidate. Supporting it means deciding where the inserted
        # parens go relative to the `not`.
        code = (
            'if not (some_condition_value and another_condition_value'
            ' and a_third_condition_v):\n'
            '    pass\n'
        )
        formatted, skipped = parsimony.format_code(code)
        assert formatted == code
        assert [lineno for lineno, _text in skipped] == [1]

    def a_spine_inside_a_bracket_is_reported_not_broken(self):
        # A single-item call is never opened, and the spine inside it is
        # not a test expression, so the line stays over-long.
        code = (
            'if some_check_function(alpha_value_here and beta_value_here'
            ' and gamma_value_xyzz):\n'
            '    pass\n'
        )
        formatted, skipped = parsimony.format_code(code)
        assert formatted == code
        assert [lineno for lineno, _text in skipped] == [1]

    def an_assert_condition_is_reported_not_broken(self):
        code = (
            'assert some_condition_value and another_condition_value'
            ' and a_third_condition_xyz\n'
        )
        formatted, skipped = parsimony.format_code(code)
        assert formatted == code
        assert [lineno for lineno, _text in skipped] == [1]

    def a_returned_boolean_is_reported_not_broken(self):
        code = (
            'def f():\n'
            '    return some_condition_value and another_condition_value'
            ' and a_third_condition\n'
        )
        formatted, skipped = parsimony.format_code(code)
        assert formatted == code
        assert [lineno for lineno, _text in skipped] == [2]
