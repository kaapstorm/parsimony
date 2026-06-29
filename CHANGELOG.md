Changelog
=========

[0.1.3] (2026-06-29)
--------------------

### Fixed

- No longer reformats code inside f-string interpolations.

[0.1.3]: https://github.com/kaapstorm/parsimony/releases/tag/v0.1.3


[0.1.2] (2026-06-28)
--------------------

### Internal

- Added Python 3.11 as a supported version

[0.1.2]: https://github.com/kaapstorm/parsimony/releases/tag/v0.1.2


[0.1.1] (2026-06-26)
--------------------

Rename the project to "kaapstorm-parsimony" to resolve a clash on PyPI.

[0.1.1]: https://github.com/kaapstorm/parsimony/releases/tag/v0.1.1


[0.1.0] (2026-06-26)
--------------------

Initial release.

### Added

- Minimalist line-breaker that adds the fewest breaks needed to fit an
  over-long line, using two complementary strategies:
  - **Bracket exploding** — opens the outermost multi-item container on
    an over-long line, one element per line at a +4 hanging indent with a
    trailing comma, coalescing adjacent single-item wrappers.
  - **Method-chain breaking** — the fallback when no bracket can shorten
    the line: wraps a chain of >= 2 call segments in parentheses and puts
    the head plus each `.attr` on its own line.
- Idempotent by design: only adds breaks to physically over-long lines,
  never removes or re-flows existing breaks.
- `parsimony` command-line tool reading from files/directories or stdin,
  with `-i`/`--in-place` and `--check` (diff + non-zero exit) modes, and
  reporting of lines it cannot fix.
- `format_code()` exposed as the public Python API.
- Support for Python 3.12, 3.13, and 3.14.

[0.1.0]: https://github.com/kaapstorm/parsimony/releases/tag/v0.1.0
