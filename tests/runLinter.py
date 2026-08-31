#!/usr/bin/env python3
# deployed from Glawster/organiseMyProjects release 0.5 -- do not edit directly
"""CLI entry point for the GUI Naming Linter."""

import argparse
import os

from organiseMyProjects.fixMarkup import markupFix
from organiseMyProjects.guiNamingLinter import lintFile, lintGuiNaming


def _lintTarget(target: str) -> None:
    """Lint a single file or directory."""
    print(f"Linting: {target}")
    if os.path.isdir(target):
        lintGuiNaming(target)
    else:
        lintFile(target)


def main() -> None:

    parser = argparse.ArgumentParser(
        description="Run GUI naming linting and optional markup linting"
    )
    parser.add_argument(
        "targets",
        nargs="*",
        help="File or directory to lint; defaults to the current project",
    )
    parser.add_argument(
        "--markup",
        action="store_true",
        help="Run markdown lint checks using markdownlint-cli",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="With --markup, apply automatic markup fixes where possible",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="With --markup, enable strict markdown rules and report findings as warnings",
    )
    parser.add_argument(
        "--fix-markup",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    if args.fix and not args.markup:
        parser.error("--fix requires --markup")
    if args.strict and not args.markup:
        parser.error("--strict requires --markup")

    # Markup mode is intentionally isolated so markdown checks can be run
    # without triggering Python GUI naming lint.
    if args.markup or args.fix_markup:
        fixMode = bool(args.fix or args.fix_markup)
        markupExitCode = markupFix(
            targets=args.targets or None,
            fix=fixMode,
            strict=args.strict,
        )
        if markupExitCode != 0:
            raise SystemExit(markupExitCode)
        return

    for target in args.targets:
        if not os.path.exists(target):
            print(f"Target '{target}' does not exist. Skipping...")
            continue
        if not os.access(target, os.R_OK):
            print(f"Target '{target}' is not readable. Skipping...")
            continue
        if not os.path.isdir(target) and not target.endswith(".py"):
            print(f"Target '{target}' is not a Python file or directory. Skipping...")
            continue
        _lintTarget(target)

    # Only search for project directories if no targets were provided
    if not args.targets:
        print("No target supplied. Searching for project directories to lint...")
        found = False
        for folder in ("src", "ui", "tests"):
            if os.path.isdir(folder):
                _lintTarget(folder)
                found = True

        if not found:
            _lintTarget(".")


if __name__ == "__main__":
    main()
