#!/usr/bin/env python3
"""
JobContextMCP CLI
-----------------
Invoke any registered MCP tool directly from the terminal without needing
an AI client — useful for development, debugging, and scripted updates.

Usage:
    .venv/bin/python3 cli.py <tool_name> [json_kwargs]

Examples:
    .venv/bin/python3 cli.py log_person '{"name":"Hawk","relationship":"beta tester","company":"unknown","context":"Friend of Brian, job searching."}'
    .venv/bin/python3 cli.py update_post_metrics '{"post_id":10,"impressions":163,"reactions":4}'
    .venv/bin/python3 cli.py update_application '{"company":"Airbnb","role":"Software Engineer, Listings Platform","status":"phone screen complete"}'
    .venv/bin/python3 cli.py get_job_hunt_status
    .venv/bin/python3 cli.py --list

Notes:
    - json_kwargs is optional for no-argument tools
    - Use single quotes around the JSON string in zsh/bash to avoid shell escaping issues
    - String values with apostrophes inside JSON should use unicode escape: \\u0027
"""

import sys
import json
import inspect


# ── Tool discovery ─────────────────────────────────────────────────────────────

class _Collector:
    """Minimal stand-in for FastMCP — just collects tool functions via .tool()."""
    def __init__(self):
        self._tools: dict[str, callable] = {}

    def tool(self):
        def decorator(fn):
            self._tools[fn.__name__] = fn
            return fn
        return decorator


def _discover_tools() -> dict[str, callable]:
    from tools import (
        session, job_hunt, resume, fitment, interview,
        project_scanner, health, context, tone, rag, star,
        outreach, export, people, generate, setup, posts,
        rejections, digest, compensation, ingest, hbdi,
    )
    collector = _Collector()
    for mod in [
        session, job_hunt, resume, fitment, interview,
        project_scanner, health, context, tone, rag, star,
        outreach, export, people, generate, setup, posts,
        rejections, digest, compensation, ingest, hbdi,
    ]:
        mod.register(collector)
    return collector._tools


# ── Helpers ────────────────────────────────────────────────────────────────────

def _print_tools(tools: dict) -> None:
    print(f"\nAvailable tools ({len(tools)}):\n")
    for name, fn in sorted(tools.items()):
        sig = inspect.signature(fn)
        params = ", ".join(
            p for p in sig.parameters
            if p not in ("self",)
        )
        print(f"  {name}({params})")
    print()


def _print_usage() -> None:
    print(__doc__)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        _print_usage()
        sys.exit(0)

    tools = _discover_tools()

    if args[0] in ("--list", "-l"):
        _print_tools(tools)
        sys.exit(0)

    tool_name = args[0]

    if tool_name not in tools:
        # Fuzzy suggestion
        close = [n for n in tools if tool_name.lower() in n.lower()]
        print(f"\nError: no tool named '{tool_name}'.")
        if close:
            print(f"Did you mean: {', '.join(close)}?")
        else:
            print("Run with --list to see all available tools.")
        sys.exit(1)

    fn = tools[tool_name]

    # Parse kwargs
    kwargs: dict = {}
    if len(args) > 1:
        try:
            kwargs = json.loads(args[1])
        except json.JSONDecodeError as e:
            print(f"\nError: invalid JSON kwargs — {e}")
            print(f"Received: {args[1]!r}")
            sys.exit(1)

    # Call tool
    try:
        result = fn(**kwargs)
        print(result)
    except TypeError as e:
        print(f"\nError calling {tool_name}: {e}")
        sig = inspect.signature(fn)
        print(f"Expected signature: {tool_name}{sig}")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
