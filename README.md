Parsimony
=========

A minimalist line-breaker that adds the fewest breaks to fit the line.

Unlike black/blue/ruff, which explode the outermost bracket first and
stack every closing bracket on its own line, Parsimony makes the
smallest change that fits an over-long line, using two complementary
strategies.

**Explode a bracket** — open the minimum number of brackets and coalesce
adjacent ones:

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

**Break a method chain** — split a long `.`-chain one segment per line.
This is done for lines that can't be shortened by exploding a bracket:

```python
queryset = SomeModel.objects.filter(active=True).order_by('-last_modified_at')
```

becomes

```python
queryset = (
    SomeModel
    .objects
    .filter(active=True)
    .order_by('-last_modified_at')
)
```

Both keep related calls grouped and give long pipelines a clean
one-operation-per-line shape.


Usage
-----

Format files or directories (recurses for `*.py`):

```shell
parsimony -i src/       # rewrite in place
parsimony --check src/  # print a diff, exit 1 if anything would change
parsimony src/file.py   # print formatted output to stdout
```

Read from stdin and write to stdout:

```shell
parsimony < src/file.py
cat src/file.py | parsimony
```


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


Limitations
-----------

- Lines long for non-bracket, non-method-chain reasons — ternaries,
  boolean/arithmetic chains, pure attribute chains (no calls), long
  string literals — are left untouched and reported, not fixed.
- No "join" pass: it will not re-flow code that another tool has already
  split. It only acts on lines that are physically too long.
- Comments inside brackets and pre-existing trailing commas are not
  specially handled.
