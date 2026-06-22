from datetime import date, timedelta
import subprocess

from tools import github as gh


def test_get_github_stats_offline_and_live_formatting(isolated_server, monkeypatch):
    monkeypatch.setattr(gh, "_is_offline", lambda: True)
    out_offline = gh.get_github_stats("octocat")
    assert "GitHub profile" in out_offline

    monkeypatch.setattr(gh, "_is_offline", lambda: False)
    responses = [
        {"login": "octocat", "name": "Octo", "bio": "bio", "public_repos": 2, "followers": 3, "following": 4, "html_url": "https://github.com/octocat"},
        [
            {"name": "repo", "description": "desc", "language": "Python", "stargazers_count": 5, "html_url": "https://github.com/octocat/repo", "fork": False},
            {"name": "forked", "description": "", "language": "", "stargazers_count": 99, "html_url": "x", "fork": True},
        ],
    ]
    monkeypatch.setattr(gh, "_http_get_json", lambda *_a, **_k: responses.pop(0))
    out_live = gh.get_github_stats("octocat")
    assert "Top non-fork repos" in out_live
    assert "repo" in out_live and "forked" not in out_live


def test_resolve_token_and_fetch_traffic_error_paths(isolated_server, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "  tok  ")
    assert gh._resolve_token() == "tok"
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    monkeypatch.setattr(
        gh.subprocess,
        "run",
        lambda *_a, **_k: type("R", (), {"returncode": 0, "stdout": "gh-token\\n"})(),
    )
    assert gh._resolve_token().startswith("gh-token")
    monkeypatch.setattr(gh.subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="gh", timeout=1)))
    assert gh._resolve_token() is None

    monkeypatch.setattr(gh.urllib.request, "urlopen", lambda *_a, **_k: (_ for _ in ()).throw(OSError("x")))
    assert gh._fetch_traffic("o/r", "clones", "tok") is None


def test_merge_buckets_and_window_sum_and_refresh_one(isolated_server, monkeypatch):
    existing = {}
    gh._merge_buckets(existing, {"clones": [{"timestamp": "2026-06-01T00:00:00Z", "count": 3, "uniques": 2}]}, "clones")
    gh._merge_buckets(existing, {"clones": [{"timestamp": "2026-06-01T00:00:00Z", "count": 4, "uniques": 2}]}, "clones")
    assert existing["clones"]["2026-06-01"]["count"] == 4

    today = date.today().isoformat()
    old = (date.today() - timedelta(days=40)).isoformat()
    c, u = gh._window_sum({today: {"count": 5, "uniques": 3}, old: {"count": 9, "uniques": 8}, "bad": {}}, 14)
    assert (c, u) == (5, 3)

    repos_hist = {}

    def fake_fetch(slug, kind, token):
        if kind == "clones":
            return {"clones": [{"timestamp": "2026-06-01T00:00:00Z", "count": 2, "uniques": 1}]}
        return None

    monkeypatch.setattr(gh, "_fetch_traffic", fake_fetch)
    assert gh._refresh_one("o/r", "tok", repos_hist) is True
    assert "clones" in repos_hist["o/r"]


def test_refresh_portfolio_metrics_main_paths(isolated_server, monkeypatch):
    import lib.config as cfg

    monkeypatch.setattr(cfg, "get_github_metrics_config", lambda: {"username": "u", "repos": []})
    assert "no repos configured" in gh.refresh_portfolio_metrics().lower()

    monkeypatch.setattr(cfg, "get_github_metrics_config", lambda: {"username": "u", "repos": ["repo1", "repo2"]})
    monkeypatch.setattr(gh, "_resolve_token", lambda: None)
    assert "no github token" in gh.refresh_portfolio_metrics().lower()

    monkeypatch.setattr(gh, "_resolve_token", lambda: "tok")
    monkeypatch.setattr(gh, "_load_history", lambda: {"tracking_since": None, "last_refreshed": None, "repos": {}})
    saved = {}
    monkeypatch.setattr(gh, "_save_history", lambda data: saved.update(data))

    def fake_refresh(slug, token, repos_hist):
        if slug.endswith("repo1"):
            repos_hist.setdefault(slug, {"clones": {"2026-06-01": {"count": 7, "uniques": 3}}})
            return True
        return False

    monkeypatch.setattr(gh, "_refresh_one", fake_refresh)
    out = gh.refresh_portfolio_metrics()
    assert "Portfolio metrics refreshed" in out
    assert "repo1" in out and "traffic unavailable" in out
    assert saved["tracking_since"] == "2026-06-01"


def test_get_portfolio_metrics_formats_aggregate(isolated_server, monkeypatch):
    monkeypatch.setattr(gh, "_load_history", lambda: {"repos": {}})
    assert "No portfolio metrics recorded yet" in gh.get_portfolio_metrics()

    monkeypatch.setattr(gh, "_load_history", lambda: {
        "tracking_since": "2026-01-01",
        "last_refreshed": "2026-06-20T00:00:00Z",
        "repos": {
            "u/repo-a": {"clones": {date.today().isoformat(): {"count": 4, "uniques": 2}}},
            "u/repo-b": {"clones": {date.today().isoformat(): {"count": 1, "uniques": 1}}},
        },
    })
    out = gh.get_portfolio_metrics()
    assert "GitHub portfolio traffic" in out
    assert "TOTAL across 2 repos" in out
    assert "repo-a" in out and "repo-b" in out
