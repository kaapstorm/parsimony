"""Command-line interface for parsimony."""
import argparse
import difflib
import sys
from pathlib import Path

from parsimony.core import LINE_LENGTH
from parsimony.formatter import format_code

DESCRIPTION = 'A minimalist line-breaker that adds the fewest breaks to fit the line.'


def iter_paths(paths):
    for p in paths:
        path = Path(p)
        if path.is_dir():
            yield from sorted(path.rglob('*.py'))
        else:
            yield path


def report_skipped(name, skipped):
    for lineno, text in skipped:
        print(
            f'{name}:{lineno}: Line length still over {LINE_LENGTH}: '
            f'{text.strip()[:60]}…',
            file=sys.stderr
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('paths', nargs='*', help='files/dirs (default: stdin)')
    parser.add_argument('-i', '--in-place', action='store_true')
    parser.add_argument(
        '--check',
        action='store_true',
        help="Exit 1 if any file would change. Print a diff, don't write.",
    )
    args = parser.parse_args(argv)

    if not args.paths:
        formatted, skipped = format_code(sys.stdin.read())
        sys.stdout.write(formatted)
        report_skipped('<stdin>', skipped)
        return 0

    changed = False
    for path in iter_paths(args.paths):
        original = path.read_text()
        try:
            formatted, skipped = format_code(original)
        except Exception as exc:  # noqa: BLE001 - dry-run resilience
            print(f'{path}: ERROR {type(exc).__name__}: {exc}', file=sys.stderr)
            continue
        report_skipped(str(path), skipped)
        if formatted == original:
            continue
        changed = True
        if args.check:
            sys.stdout.writelines(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    formatted.splitlines(keepends=True),
                    f'a/{path}',
                    f'b/{path}',
                )
            )
        elif args.in_place:
            path.write_text(formatted)
            print(f'reformatted {path}', file=sys.stderr)
        else:
            sys.stdout.write(formatted)

    return 1 if (args.check and changed) else 0


if __name__ == '__main__':
    sys.exit(main())
