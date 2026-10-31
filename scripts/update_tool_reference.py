"""Refresh the checked-in public tool reference from the dispatch registry.

Run from the repository root: python -m scripts.update_tool_reference
Only capability headings and action tables are replaced; explanatory prose stays.
"""
import inspect
from pathlib import Path
import re

from tools.consolidated import DOMAINS


def update_reference(text: str) -> str:
    total = sum(map(len, DOMAINS.values()))
    text = re.sub(r"# MCP Tool Reference[^\n]*", f"# MCP Tool Reference — {len(DOMAINS)} Domain Tools, {total} Actions", text)
    for domain, actions in DOMAINS.items():
        heading = f"## {domain} — {len(actions)} actions"
        pattern = rf"## {domain} — \d+ actions"
        text, matches = re.subn(pattern, heading, text)
        if matches != 1:
            raise ValueError(f"Expected one heading for {domain}")
        rows = ["| Action | Purpose | Required | Optional |", "|---|---|---|---|"]
        for action, (target, summary) in actions.items():
            params = inspect.signature(target).parameters.values()
            required, optional = [], []
            for param in params:
                (required if param.default is inspect.Parameter.empty else optional).append(f"`{param.name}`")
            purpose = summary.replace("|", "\\|").replace("\n", " ")
            rows.append(f"| `{action}` | {purpose} | {', '.join(required) or '—'} | {', '.join(optional) or '—'} |")
        start = text.index(heading)
        table_start = text.index("| Action |", start)
        table_end = text.index("\n\n", table_start)
        text = text[:table_start] + "\n".join(rows) + text[table_end:]
    return text


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "docs/tools.md"
    path.write_text(update_reference(path.read_text(encoding="utf-8")), encoding="utf-8")
