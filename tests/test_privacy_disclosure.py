"""Keep the public storage notice discoverable and its source copy in sync."""
from html.parser import HTMLParser
from pathlib import Path
import re

import pytest

from transport.http.routes.privacy import privacy_html


class _StorageNotice(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.parts = []
        self.links = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "h2":
            self.active = values.get("id") == "cookies-and-browser-storage"
        if tag == "a":
            self.links[values.get("href")] = True

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)


def _words(text):
    return re.sub(r"\s+", " ", text).strip()


def test_public_storage_notice_matches_the_markdown_source():
    page = _StorageNotice()
    page.feed(privacy_html())
    policy = (Path(__file__).parents[1] / "docs/files/jobcontext-privacy-policy.md").read_text()
    notice = policy.split("## Cookies and browser storage\n", 1)[1].split("\n## ", 1)[0]
    markdown_text = "Cookies and browser storage " + notice.replace("`", "")
    markdown_text = re.sub(r"(?m)^- ", "", markdown_text)
    assert _words("".join(page.parts)) == _words(markdown_text)


@pytest.mark.parametrize("path", ["/login", "/dashboard/login"])
def test_signin_surfaces_link_to_storage_notice_and_terms(http_client_authed, path):
    response = http_client_authed.get(path)
    assert response.status_code == 200
    page = _StorageNotice()
    page.feed(response.text)
    assert "/privacy#cookies-and-browser-storage" in page.links
    assert "/terms" in page.links
    privacy = http_client_authed.get("/privacy")
    assert 'id="cookies-and-browser-storage"' in privacy.text


def test_storage_notice_is_public_without_setting_a_cookie(http_client_authed):
    response = http_client_authed.get("/privacy")
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    for item in ("jc_session", "pkce_verifier", "__Host-jc_login_csrf", "oura_state", "jc-evals-golden-draft"):
        assert item in response.text
    assert "sessionStorage" in response.text
    assert "Microsoft and Oura" in response.text
