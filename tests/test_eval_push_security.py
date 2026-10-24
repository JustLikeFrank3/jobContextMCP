"""Eval pushes only contact the explicit HTTP(S) endpoint, never redirects."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from threading import Thread
import urllib.error
import urllib.request

import pytest

from evals import push


@contextmanager
def local_server(status=200, location=None, body=b'{"stored": "suite"}'):
    """Disposable loopback-only endpoint; no QA/production traffic or secrets."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append({
                "method": self.command,
                "path": self.path,
                "auth": self.headers.get("Authorization"),
                "content_type": self.headers.get("Content-Type"),
                "body": self.rfile.read(int(self.headers.get("Content-Length", 0))),
            })
            self.send_response(status)
            if location is not None:
                self.send_header("Location", location)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.fixture(autouse=True)
def bypass_proxies_for_loopback(monkeypatch):
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


@pytest.mark.parametrize("url", [
    "file:///tmp/not-an-eval-server", "ftp://example.test", "data:text/plain,{}",
    "javascript:alert(1)", "//example.test", "example.test", "http://", "http:///path",
    "https://user:password@example.test", "https://user@example.test",
    "https://example.test?query=1", "https://example.test?", "https://example.test#fragment",
    "https://example.test#", " https://example.test", "\nhttps://example.test",
    "ht\ttps://example.test", "https://example.test/\rpath", "http://example.test/\x00",
    "http://example.test/\x7f", "http://example.test:invalid", "http://example.test:65536",
    "http://[::1", "http://example.test\\@other.test",
])
def test_invalid_urls_rejected_before_opening(monkeypatch, url):
    def unexpected_opener(*args):
        pytest.fail("invalid destination reached the network opener")

    monkeypatch.setattr(push.urllib.request, "build_opener", unexpected_opener)
    with pytest.raises(ValueError):
        push.push_results({"rows": []}, url, api_key="synthetic-token")


@pytest.mark.parametrize(("url", "expected"), [
    ("http://localhost:1234/", "http://localhost:1234/api/evals/results"),
    ("https://example.test/base/path/", "https://example.test/base/path/api/evals/results"),
    ("HTTPS://example.test", "https://example.test/api/evals/results"),
    ("http://[::1]:1234", "http://[::1]:1234/api/evals/results"),
])
def test_valid_base_urls(url, expected):
    assert push._results_url(url) == expected


@pytest.mark.parametrize("api_key", ["", "synthetic-token"])
def test_real_http_push_preserves_json_auth_and_base_path(api_key):
    payload = {"rows": [{"id": "synthetic", "score": 0.5}]}
    with local_server() as (url, received):
        assert push.push_results(payload, url + "/prefix/", api_key=api_key) == {"stored": "suite"}
    assert received == [{
        "method": "POST", "path": "/prefix/api/evals/results",
        "auth": f"Bearer {api_key}" if api_key else None,
        "content_type": "application/json", "body": json.dumps(payload).encode("utf-8"),
    }]


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_same_origin_redirects_never_replayed(status):
    with local_server(status=status, location="/redirect-target") as (url, received):
        with pytest.raises(urllib.error.HTTPError) as caught:
            push.push_results({"rows": []}, url, api_key="synthetic-token")
        assert caught.value.code == status
        caught.value.close()
    assert len(received) == 1
    assert received[0]["path"] == "/api/evals/results"


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_cross_origin_redirects_never_receive_credentials_or_payload(status):
    with local_server() as (other_origin, other_received):
        with local_server(status=status, location=other_origin + "/capture") as (url, received):
            with pytest.raises(urllib.error.HTTPError) as caught:
                push.push_results({"rows": []}, url, api_key="synthetic-token")
            assert caught.value.code == status
            caught.value.close()
        assert len(received) == 1
        assert other_received == []


@pytest.mark.parametrize("location", ["file:///tmp/not-an-eval-server", "ftp://example.test"])
def test_non_http_redirects_rejected(monkeypatch, location):
    def unexpected_protocol(*args):
        pytest.fail("redirect reached a non-HTTP protocol handler")

    monkeypatch.setattr(urllib.request.FileHandler, "file_open", unexpected_protocol)
    monkeypatch.setattr(urllib.request.FTPHandler, "ftp_open", unexpected_protocol)
    with local_server(status=302, location=location) as (url, received):
        with pytest.raises(urllib.error.HTTPError) as caught:
            push.push_results({"rows": []}, url, api_key="synthetic-token")
        caught.value.close()
    assert len(received) == 1


def test_https_downgrade_redirect_rejected():
    request = urllib.request.Request("https://example.test/api/evals/results", data=b"{}")
    with pytest.raises(urllib.error.HTTPError):
        push._NoRedirect().redirect_request(
            request, None, 302, "Found", {}, "http://example.test/api/evals/results"
        )


@pytest.mark.parametrize("status", [401, 404, 500, 503])
def test_http_errors_are_not_reported_as_success(status):
    with local_server(status=status) as (url, received):
        with pytest.raises(urllib.error.HTTPError) as caught:
            push.push_results({"rows": []}, url)
        assert caught.value.code == status
        caught.value.close()
    assert len(received) == 1


def test_invalid_json_is_not_reported_as_success():
    with local_server(body=b"not-json") as (url, _):
        with pytest.raises(json.JSONDecodeError):
            push.push_results({"rows": []}, url)
