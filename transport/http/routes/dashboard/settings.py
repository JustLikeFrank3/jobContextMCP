"""User settings dashboard — /dashboard/settings.

GET  /dashboard/settings        — show settings page
POST /dashboard/settings/ai-key — save / clear OpenAI API key in user config.json
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse

from transport.http.auth import require_authenticated_user
from transport.http.security import User
from .shared import BASE_CSS, html_page, nav_tabs, page_header
from .assets import logo_svg

router = APIRouter()

_EXTRA_CSS = """
  .settings-section {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 22px 24px;
    margin-bottom: 20px;
  }
  .settings-section h2 {
    margin: 0 0 6px;
    font-size: 1rem;
    color: var(--accent);
  }
  .settings-section .desc {
    color: var(--muted);
    font-size: 0.86rem;
    margin-bottom: 16px;
    line-height: 1.55;
  }
  .key-status {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.85rem;
    font-weight: 600;
    margin-bottom: 14px;
  }
  .key-status.set   { color: var(--ok); }
  .key-status.unset { color: var(--muted); }
  .form-row {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
  }
  .key-input {
    background: #0e1628;
    color: var(--text);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 9px 12px;
    font-size: 0.88rem;
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    flex: 1;
    min-width: 240px;
  }
  .key-input:focus { outline: none; border-color: var(--accent); }
  .save-btn {
    background: var(--accent);
    color: #0b1220;
    border: none;
    border-radius: 8px;
    padding: 9px 18px;
    font-size: 0.88rem;
    font-weight: 700;
    cursor: pointer;
    white-space: nowrap;
  }
  .save-btn:hover { opacity: 0.85; }
  .clear-btn {
    background: none;
    border: 1px solid var(--danger);
    color: var(--danger);
    border-radius: 8px;
    padding: 9px 14px;
    font-size: 0.85rem;
    cursor: pointer;
    white-space: nowrap;
  }
  .clear-btn:hover { background: color-mix(in srgb, var(--danger) 10%, transparent); }
  .flash-ok {
    background: color-mix(in srgb, var(--ok) 10%, var(--panel));
    border: 1.5px solid var(--ok);
    border-radius: 10px;
    padding: 12px 18px;
    margin-bottom: 18px;
    color: var(--ok);
    font-size: 0.9rem;
    font-weight: 600;
  }
  .flash-err {
    background: color-mix(in srgb, var(--danger) 10%, var(--panel));
    border: 1.5px solid var(--danger);
    border-radius: 10px;
    padding: 12px 18px;
    margin-bottom: 18px;
    color: var(--danger);
    font-size: 0.9rem;
  }
  .note-box {
    background: color-mix(in srgb, var(--accent) 7%, var(--panel));
    border: 1px solid color-mix(in srgb, var(--accent) 25%, transparent);
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 0.83rem;
    color: var(--muted);
    line-height: 1.6;
    margin-top: 14px;
  }
"""


def _user_config_path(user: User) -> Path | None:
    """Return the path to the user's config.json, or None if no data dir."""
    try:
        from lib.user_context import get_data_folder_override
        override = get_data_folder_override()
        if override:
            return override / "config.json"
    except Exception:
        pass
    return None


def _read_user_config(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _write_user_config(path: Path, cfg: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _build_page(user: User, flash: str = "", flash_type: str = "ok") -> str:
    config_path = _user_config_path(user)
    cfg = _read_user_config(config_path) if config_path else {}
    has_key = bool(cfg.get("openai_api_key", "").strip())

    flash_html = ""
    if flash:
        cls = "flash-ok" if flash_type == "ok" else "flash-err"
        flash_html = f'<div class="{cls}">{flash}</div>'

    status_html = (
        '<span class="key-status set">✓ API key configured</span>'
        if has_key else
        '<span class="key-status unset">○ No API key set — AI features disabled</span>'
    )

    clear_btn = (
        """<form method="post" action="/dashboard/settings/ai-key" style="margin:0">
          <input type="hidden" name="openai_key" value="" />
          <input type="hidden" name="action" value="clear" />
          <button class="clear-btn" type="submit"
                  onclick="return confirm('Remove your OpenAI key? AI features will be disabled until you add one.')">
            Remove key
          </button>
        </form>"""
        if has_key else ""
    )

    body = f"""
{flash_html}
<div class="settings-section">
  <h2>🤖 AI generation</h2>
  <p class="desc">
    Paste your own OpenAI API key to enable AI-powered resume generation, cover letter drafting,
    and semantic search. Your key is stored only in your private workspace and is never shared.
    You pay OpenAI directly — usage is entirely under your account.
  </p>
  {status_html}
  <form method="post" action="/dashboard/settings/ai-key" style="margin-top:12px">
    <input type="hidden" name="action" value="save" />
    <div class="form-row">
      <input class="key-input" type="password" name="openai_key"
             placeholder="sk-..." autocomplete="off" />
      <button class="save-btn" type="submit">Save key</button>
      {clear_btn}
    </div>
  </form>
  <div class="note-box">
    Get a key at <strong>platform.openai.com/api-keys</strong>.
    The free tier is enough for personal use. Set a monthly spend limit in your OpenAI dashboard
    to avoid surprises. The key is stored only in your private <code>config.json</code>
    and is never visible to other users or the server operator.
  </div>
</div>
"""
    return html_page("Settings", "settings", "Account and AI preferences", _EXTRA_CSS, body)


@router.get("/settings", include_in_schema=False)
async def settings_page(
    saved: str = "",
    user: User = Depends(require_authenticated_user),
) -> HTMLResponse:
    flash = "✓ Settings saved." if saved == "1" else ""
    return HTMLResponse(_build_page(user, flash=flash))


@router.post("/settings/ai-key", include_in_schema=False)
async def save_ai_key(
    openai_key: str = Form(default=""),
    action: str = Form(default="save"),
    user: User = Depends(require_authenticated_user),
) -> HTMLResponse:
    config_path = _user_config_path(user)
    if not config_path:
        return HTMLResponse(_build_page(
            user,
            flash="Could not locate your workspace. Please contact support.",
            flash_type="err",
        ))

    cfg = _read_user_config(config_path)
    key = openai_key.strip()

    if action == "clear" or not key:
        cfg.pop("openai_api_key", None)
        _write_user_config(config_path, cfg)
        return HTMLResponse(_build_page(user, flash="✓ API key removed.", flash_type="ok"))

    if not key.startswith("sk-"):
        return HTMLResponse(_build_page(
            user,
            flash="That doesn't look like a valid OpenAI key (should start with sk-).",
            flash_type="err",
        ))

    cfg["openai_api_key"] = key
    _write_user_config(config_path, cfg)
    return HTMLResponse(_build_page(user, flash="✓ OpenAI API key saved. AI features are now enabled."))
