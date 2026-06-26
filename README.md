Parsimony
=========

A minimalist line-breaker that adds the fewest breaks to fit the line.

Unlike black/blue/ruff, which explode the outermost bracket first and
stack every closing bracket on its own line, this tool makes the
smallest change that fits an over-long line, using two complementary
strategies: exploding a bracket, or breaking a method chain.

Exploding a bracket opens the minimum number of brackets and coalesces
adjacent ones. e.g.

```python
response = authed_client().get(reverse('forwarding:detail', args=[c.id]))
```

becomes

```python
response = authed_client().get(reverse(
    'forwarding:detail',
    args=[c.id],
))
```

rather than the deep staircase that black/ruff produce.

Breaking a method chain splits a long `.`-chain one segment per line.
It is the fallback for lines no bracket can shorten. e.g.

```python
django_queryset = SomeModel.objects.filter(active=True).order_by('-id')
```

becomes

```python
django_queryset = (
    SomeModel
    .objects
    .filter(active=True)
    .order_by('-id')
)
```

The motivation is readability: coalescing keeps related calls grouped
visually and reduces vertical noise, while chain-breaking gives long
fluent pipelines a clean one-operation-per-line shape.


Installation
------------

```shell
pip install kaapstorm-parsimony
```


Algorithm
---------

While a physical line exceeds `LINE_LENGTH`, explode one container that
intersects an over-long line, chosen by:

1. multi-item containers only (>= 2 args/elements); single-item
   containers are never opened — see "Contract" below.
2. outermost (shallowest) of those.

Then re-measure and repeat. "Explode" = each element on its own line at
a +4 hanging indent, with a trailing comma, and the closing bracket
dedented to the opening line's indent. Because we only open the chosen
container and never its single-item parents, adjacent openers like
`get(reverse(` remain coalesced. Coalescing is not about depth, only
about not opening single-item wrappers.

When no multi-item container intersects a remaining over-long line, fall
back to breaking the outermost method chain on it (>= 2 call segments,
as shown above): wrap it in parentheses and put the head plus each
`.attr` on its own +4 line. Bracket explosion is preferred — a chain is
only broken when opening a bracket cannot fix the line — which keeps
breaks minimal. Any brackets already opened inside a segment are
re-indented to stay aligned under their now-deeper segment.


Contract
--------

The tool only ever adds breaks to over-long lines; it never removes or
rewrites existing breaks. This makes it idempotent, safe to re-run, and
safe to combine with hand-formatting. Preserving existing line breaks
is intentional, so it cannot be combined with `ruff format`, which would
re-flow its output back into the staircase. Pair it with ruff-as-linter
(E501 off) instead.

Multi-item-only is also a correctness guardrail: opening a single-item
subscript would turn `x[0]` into `x[0,]` (== `x[(0,)]`), which changes
meaning. Restricting to multi-item containers avoids that. It also
avoids ugly single-element splits.


Known limitations
-----------------

- Lines long for non-bracket, non-method-chain reasons — ternaries,
  boolean/arithmetic chains, pure attribute chains (no calls), long
  string literals — are left untouched and reported, not fixed.
- No "join" pass: it will not re-flow code that another tool has already
  split. It only acts on lines that are physically too long.
- Comments inside brackets and pre-existing trailing commas are not
  specially handled.
