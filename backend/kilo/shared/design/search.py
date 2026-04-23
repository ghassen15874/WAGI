#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Search entrypoint backed by the vendored UUPM engine."""
from __future__ import annotations

import argparse
import io
import json
import sys

from .core import AVAILABLE_STACKS, CSV_CONFIG, MAX_RESULTS, search, search_stack
from .design_system import generate_design_system


if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


def format_output(result: dict) -> str:
    """Format search results for human-readable CLI output."""
    if "error" in result:
        return f"Error: {result['error']}"

    output: list[str] = []
    if result.get("stack"):
        output.append("## UI Pro Max Stack Guidelines")
        output.append(f"**Stack:** {result['stack']} | **Query:** {result['query']}")
    else:
        output.append("## UI Pro Max Search Results")
        output.append(f"**Domain:** {result['domain']} | **Query:** {result['query']}")
    output.append(f"**Source:** {result['file']} | **Found:** {result['count']} results\n")

    for index, row in enumerate(result["results"], 1):
        output.append(f"### Result {index}")
        for key, value in row.items():
            value_str = str(value)
            if len(value_str) > 300:
                value_str = value_str[:300] + "..."
            output.append(f"- **{key}:** {value_str}")
        output.append("")

    return "\n".join(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UI Pro Max Search")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--domain", "-d", choices=list(CSV_CONFIG.keys()), help="Search domain")
    parser.add_argument("--stack", "-s", choices=AVAILABLE_STACKS, help="Stack-specific search")
    parser.add_argument("--max-results", "-n", type=int, default=MAX_RESULTS, help="Max results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--design-system", "-ds", action="store_true", help="Generate a design system")
    parser.add_argument("--project-name", "-p", type=str, default=None, help="Project name")
    parser.add_argument("--format", "-f", choices=["ascii", "markdown"], default="ascii", help="Design-system format")
    parser.add_argument("--persist", action="store_true", help="Persist generated design-system files")
    parser.add_argument("--page", type=str, default=None, help="Optional page override name")
    parser.add_argument("--output-dir", "-o", type=str, default=None, help="Persistence output directory")
    args = parser.parse_args(argv)

    if args.design_system:
        print(
            generate_design_system(
                args.query,
                args.project_name,
                args.format,
                persist=args.persist,
                page=args.page,
                output_dir=args.output_dir,
            )
        )
        return 0

    if args.stack:
        result = search_stack(args.query, args.stack, args.max_results)
    else:
        result = search(args.query, args.domain, args.max_results)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_output(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
