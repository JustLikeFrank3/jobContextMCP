"""Public pages must not contact a font CDN, in source or packaged builds."""
from pathlib import Path
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import transport.http.app as app_module
from transport.http.routes.dashboard.shared import BASE_CSS


@pytest.mark.parametrize("path", [
    "/", "/why", "/setup", "/architecture", "/login", "/privacy", "/terms",
])
def test_public_templates_load_same_origin_fonts(http_client_authed, path):
    response = http_client_authed.get(path)
    assert response.status_code == 200
    assert '<link rel="stylesheet" href="/fonts/fonts.css" />' in response.text
    assert "fonts.googleapis.com" not in response.text
    assert "fonts.gstatic.com" not in response.text


def test_font_stylesheet_and_every_subset_are_public(http_client_authed):
    response = http_client_authed.get("/fonts/fonts.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "set-cookie" not in response.headers
    assert "https://" not in response.text
    subsets = re.findall(r"url\(\./([^()]+\.woff2)\)", response.text)
    assert len(subsets) == 16
    for name in subsets:
        font = http_client_authed.get(f"/fonts/{name}")
        assert font.status_code == 200
        assert font.content[:4] == b"wOF2"
        assert "set-cookie" not in font.headers
    for license_name in ("inter-OFL.txt", "jetbrainsmono-OFL.txt", "spacegrotesk-OFL.txt"):
        license_response = http_client_authed.get(f"/fonts/{license_name}")
        assert license_response.status_code == 200
        assert "SIL OPEN FONT LICENSE" in license_response.text


def test_legacy_pages_use_the_same_local_font_stylesheet():
    assert "@import url('/fonts/fonts.css');" in BASE_CSS
    assert "https://" not in BASE_CSS


@pytest.mark.parametrize("packaged", [False, True])
def test_mount_fonts_supports_source_and_packaged_assets(tmp_path, monkeypatch, packaged):
    dist = tmp_path / "bundle" / "frontend" / "dist"
    source = tmp_path / "source" / "frontend" / "public" / "fonts"
    source.mkdir(parents=True)
    (source / "fonts.css").write_text("/* source assets */")
    if packaged:
        (dist / "fonts").mkdir(parents=True)
        (dist / "fonts" / "fonts.css").write_text("/* packaged assets */")
    for directory in (source, dist / "fonts") if packaged else (source,):
        (directory.parent / "private.txt").write_text("Synthetic file outside the public font directory")
    monkeypatch.setattr(app_module, "_SPA_DIST", dist)
    monkeypatch.setattr(app_module, "_FONT_SOURCE", source)
    app = FastAPI()
    app_module._mount_fonts(app)
    with TestClient(app) as client:
        response = client.get("/fonts/fonts.css")
        assert response.status_code == 200
        assert response.text == ("/* packaged assets */" if packaged else "/* source assets */")
        assert client.get("/fonts/%2e%2e/private.txt").status_code == 404


def test_missing_assets_do_not_add_a_cdn_fallback(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(app_module, "_SPA_DIST", tmp_path / "absent-dist")
    monkeypatch.setattr(app_module, "_FONT_SOURCE", tmp_path / "absent-source")
    app = FastAPI()
    app_module._mount_fonts(app)
    with TestClient(app) as client:
        assert client.get("/fonts/fonts.css").status_code == 404
    assert "browser fallback fonts will be used" in caplog.text


def test_space_grotesk_retains_public_page_light_weight():
    css = (Path(__file__).parents[1] / "frontend" / "public" / "fonts" / "fonts.css").read_text()
    faces = re.findall(r"@font-face\s*\{([^}]+)\}", css)
    space_grotesk = [face for face in faces if "font-family: 'Space Grotesk'" in face]
    assert len(space_grotesk) == 3
    assert all("font-weight: 300 700;" in face for face in space_grotesk)
