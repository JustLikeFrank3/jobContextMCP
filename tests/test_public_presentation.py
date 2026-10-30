"""Public claims must match the default registered MCP schemas, without user data."""
import asyncio
from html.parser import HTMLParser
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_public_counts_match_registered_capabilities():
    from mcp.server.fastmcp import FastMCP
    from tools.consolidated import DOMAINS, register

    # Build the real default surface without depending on the caller's legacy mode.
    mcp = FastMCP("public-presentation-check")
    register(mcp)
    tools = asyncio.run(mcp.list_tools())
    actions = {
        tool.name: tool.inputSchema["properties"]["action"]["enum"]
        for tool in tools
    }
    assert {name: set(values) for name, values in actions.items()} == {
        name: set(values) for name, values in DOMAINS.items()
    }
    count = sum(map(len, actions.values()))
    for path in [
        "README.md", "frontend/index.html", "transport/http/routes/landing.py",
        "transport/http/routes/login_page.py", "transport/http/routes/llms.py",
        "transport/http/static/architecture/capability-layer.dot",
        "transport/http/static/architecture/capability-layer.svg",
    ]:
        text = (ROOT / path).read_text()
        claims = re.findall(r"(\d+) (?:domain )?actions", text)
        assert claims, path
        assert set(claims) == {str(count)}, path
        domains = re.findall(r"(\d+) (?:MCP |consolidated )?domain tools", text)
        assert domains and set(domains) == {str(len(tools))}, path
    landing = (ROOT / "transport/http/routes/landing.py").read_text()
    assert f'<div class="n">{count}</div>' in landing
    readme = (ROOT / "README.md").read_text()
    assert f"tools-{len(tools)}%20domains%20%C2%B7%20{count}%20actions-" in readme


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])


@pytest.mark.parametrize("path", ["/", "/why", "/setup", "/architecture", "/login", "/privacy", "/terms", "/llms.txt"])
def test_public_pages_need_no_credentials(http_client_authed, path):
    response = http_client_authed.get(path, follow_redirects=False)
    assert response.status_code == 200
    if path == "/llms.txt":
        assert response.headers["content-type"].startswith("text/plain")


def test_landing_walkthrough_links_and_examples(http_client_authed):
    response = http_client_authed.get("/")
    parser = _Links()
    parser.feed(response.text)
    for link in set(parser.links):
        if link.startswith("#"):
            assert link[1:] in parser.ids, link
        elif link.startswith("/"):
            assert http_client_authed.get(link, follow_redirects=False).status_code == 200, link
    assert 'href="#how">See how memory works' in response.text
    assert "Illustrative example" in response.text
    assert "Sample data" in response.text
    assert "requires an invitation" in response.text
    assert 'insights("session_context")' in response.text


def test_tool_reference_is_current():
    from scripts.update_tool_reference import update_reference
    text = (ROOT / "docs/tools.md").read_text()
    assert update_reference(text) == text
