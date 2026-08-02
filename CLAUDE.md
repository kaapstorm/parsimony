# Context for Claude Code

Parsimony is a minimalist code formatter.

## File locations

* Specs, plans, notes. (Files for Claude): `.claude/docs/`

## Commands

Parsimony uses **uv** to manage the project. Run commands in uv's virtual
environment with the prefix `uv run ...`

* Python: `uv run python`
* Check linting: `uv run ruff check [path/to/file.py]`
* Check typing: `uv run ty check`
* Reformat: `uv run parsimony path/to/file.py`

## Tech stack

Parsimony uses the **testsweet** test library.
[Documentation](https://github.com/kaapstorm/testsweet/blob/main/README.md)
