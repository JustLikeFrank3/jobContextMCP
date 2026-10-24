"""The architecture diagrams work without remote or executable resources."""
from html.parser import HTMLParser
import pytest

from scripts.render_architecture_diagrams import validate_svg
from transport.http.routes.architecture import architecture_html


class _Images(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []

    def handle_starttag(self, tag, attrs):
        assert tag != "script"
        if tag == "img":
            self.images.append(dict(attrs))


def test_architecture_diagrams_are_local_and_inert(http_client_authed):
    parser = _Images()
    parser.feed(architecture_html())
    assert len(parser.images) == 2
    for image in parser.images:
        assert image["src"].startswith("/static/architecture/")
        assert image["alt"]
        response = http_client_authed.get(image["src"])
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert "<!DOCTYPE" not in response.text
        validate_svg(response.text)


@pytest.mark.parametrize("content", [
    '<script>alert(1)</script>', '<style>@import "https://evil.example/x";</style>',
    '<image href="https://evil.example/x"/>', '<rect onclick="alert(1)"/>',
    '<rect fill="url(https://evil.example/x)"/>', '<foreignObject/>',
    '<rect fill="url(/external.svg)"/>', '<animate attributeName="href"/>',
])
def test_svg_validation_rejects_active_or_external_content(content):
    with pytest.raises(ValueError):
        validate_svg(f'<svg xmlns="http://www.w3.org/2000/svg">{content}</svg>')
