#!/usr/bin/env python3
"""
JobContextMCP CLI
-----------------
Invoke any registered MCP tool directly from the terminal without needing
an AI client — useful for development, debugging, and scripted updates.

Usage:
    .venv/bin/python3 cli.py <tool_name> [json_kwargs | @file.json | @-]

Examples:
    .venv/bin/python3 cli.py log_person '{"name":"Hawk","relationship":"beta tester"}'
    .venv/bin/python3 cli.py log_person @/tmp/hawk.json
    .venv/bin/python3 cli.py log_person @-          # reads JSON from stdin
    cat hawk.json | .venv/bin/python3 cli.py log_person @-
    .venv/bin/python3 cli.py update_post_metrics '{"post_id":10,"impressions":163,"reactions":4}'
    .venv/bin/python3 cli.py get_job_hunt_status
    .venv/bin/python3 cli.py --list

Notes:
    - json_kwargs is optional for no-argument tools
    - Use @filename to read JSON from a file — avoids all shell quoting issues
    - Use @- to read JSON from stdin (pipe-friendly)
    - Use single quotes around inline JSON in zsh/bash
    - String values with apostrophes inside inline JSON should use unicode escape: \\u0027
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
        session, job_hunt, resume, fitment, interview, interviews,
        project_scanner, health, context, tone, rag, star,
        outreach, export, people, generate, setup, posts,
        rejections, digest, compensation, ingest, hbdi, crossref,
        github, job_scraper, job_queue,
    )
    collector = _Collector()
    for mod in [
        session, job_hunt, resume, fitment, interview, interviews,
        project_scanner, health, context, tone, rag, star,
        outreach, export, people, generate, setup, posts,
        rejections, digest, compensation, ingest, hbdi, crossref,
        github, job_scraper, job_queue,
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


def _print_schedule_instructions(tool_name: str, run_at: str = "08:00") -> None:
    """Emit ready-to-use crontab + launchd plist to schedule a CLI tool.

    Does NOT install anything on disk — copy/paste output into the appropriate
    system to enable. Keeps the CLI portable and side-effect-free.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent
    python_bin = repo_root / ".venv" / "bin" / "python"
    cli_path = repo_root / "cli.py"

    try:
        hour, minute = (int(p) for p in run_at.split(":", 1))
    except Exception:
        print(f"Error: --time must be HH:MM (got {run_at!r})")
        sys.exit(1)

    output_dir = repo_root / "data" / "scheduled"
    log_path = output_dir / f"{tool_name}.log"

    print(f"# Schedule: run {tool_name} daily at {run_at}")
    print()
    print("# ──── crontab entry (cron / linux / older mac) ────")
    print("# Run `crontab -e` and append:")
    print(
        f"{minute} {hour} * * * {python_bin} {cli_path} {tool_name} "
        f">> {log_path} 2>&1"
    )
    print()
    print("# ──── launchd plist (macOS, recommended) ────")
    label = f"com.frankmacbride.jobcontextmcp.{tool_name}"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    print(f"# Save to: {plist_path}")
    print(f"# Then run: launchctl load {plist_path}")
    print()
    print(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_bin}</string>
        <string>{cli_path}</string>
        <string>{tool_name}</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>{hour}</integer>
        <key>Minute</key><integer>{minute}</integer>
    </dict>
    <key>StandardOutPath</key><string>{log_path}</string>
    <key>StandardErrorPath</key><string>{log_path}</string>
    <key>WorkingDirectory</key><string>{repo_root}</string>
</dict>
</plist>""")
    print()
    print(f"# Log output will accumulate at: {log_path}")
    print(f"# Make sure the directory exists: mkdir -p {output_dir}")


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

    if args[0] in ("--schedule",):
        if len(args) < 2:
            print("Error: --schedule requires a tool name (e.g. --schedule get_daily_digest)")
            sys.exit(1)
        tool_name = args[1]
        if tool_name not in tools:
            print(f"Error: no tool named '{tool_name}'. Run --list to see all tools.")
            sys.exit(1)
        # Optional --time HH:MM (default 08:00)
        run_at = "08:00"
        if "--time" in args:
            i = args.index("--time")
            if i + 1 < len(args):
                run_at = args[i + 1]
        _print_schedule_instructions(tool_name, run_at)
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

    # Parse kwargs — supports inline JSON, @filename, or @- for stdin
    kwargs: dict = {}
    if len(args) > 1:
        raw = args[1]
        try:
            if raw.startswith("@"):
                source = raw[1:]
                if source == "-":
                    json_text = sys.stdin.read()
                else:
                    from pathlib import Path
                    json_text = Path(source).read_text(encoding="utf-8")
                kwargs = json.loads(json_text)
            else:
                kwargs = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"\nError: invalid JSON kwargs — {e}")
            print(f"Received: {raw!r}")
            sys.exit(1)
        except FileNotFoundError:
            print(f"\nError: JSON file not found: {raw[1:]}")
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
