"""API key management dashboard — /dashboard/api-keys.

GET  /dashboard/api-keys          — list keys + instructions
POST /dashboard/api-keys          — generate a new key (returns page with plaintext once)
POST /dashboard/api-keys/{id}/revoke — revoke a key
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from lib.api_keys import create_key, list_keys, revoke_key
from transport.http.auth import require_authenticated_user
from transport.http.security import User
from .shared import BASE_CSS, html_page, nav_tabs, page_header
from .assets import logo_svg

router = APIRouter()

_EXTRA_CSS = """
  .info-box {
    background: color-mix(in srgb, var(--accent) 8%, var(--panel));
    border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
    border-radius: 12px; padding: 18px 20px; margin-bottom: 20px;
  }
  .info-box h2 { margin: 0 0 10px; font-size: 1rem; color: var(--accent); }
  .info-box ol { margin: 8px 0 0 18px; padding: 0; color: var(--muted); font-size: 0.88rem; line-height: 1.7; }
  .info-box ol li { margin-bottom: 4px; }
  .info-box code {
    background: #0b1624; border: 1px solid var(--line);
    border-radius: 4px; padding: 1px 6px; font-size: 0.83rem;
    color: #d1fbfb; white-space: nowrap;
  }
  .info-box .note {
    margin-top: 10px; font-size: 0.82rem; color: var(--muted);
    border-top: 1px solid var(--line); padding-top: 10px;
  }
  .flash {
    background: color-mix(in srgb, var(--ok) 10%, var(--panel));
    border: 1.5px solid var(--ok);
    border-radius: 12px; padding: 18px 20px; margin-bottom: 20px;
  }
  .flash h2 { margin: 0 0 8px; font-size: 1rem; color: var(--ok); }
  .flash .warn-note {
    font-size: 0.82rem; color: var(--warn);
    background: color-mix(in srgb, var(--warn) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--warn) 30%, transparent);
    border-radius: 8px; padding: 8px 12px; margin-bottom: 12px;
  }
  .key-display {
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  }
  .key-display code {
    font-family: 'Menlo', 'Consolas', monospace;
    background: #060d1a; border: 1px solid var(--accent);
    border-radius: 8px; padding: 10px 14px; font-size: 0.9rem;
    color: #d1fbfb; letter-spacing: 0.3px; word-break: break-all; flex: 1;
  }
  .copy-btn {
    background: var(--accent); color: #0b1220;
    border: none; border-radius: 8px; padding: 8px 16px;
    font-size: 0.82rem; font-weight: 700; cursor: pointer;
    white-space: nowrap; flex-shrink: 0;
  }
  .copy-btn:hover { opacity: 0.85; }
  .shortcut-steps {
    margin-top: 12px; font-size: 0.85rem; color: var(--muted); line-height: 1.65;
  }
  .shortcut-steps strong { color: var(--text); }
  .key-table { width: 100%; border-collapse: collapse; font-size: 0.87rem; }
  .key-table th {
    text-align: left; color: var(--muted); font-weight: 600;
    font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.4px;
    padding: 0 10px 8px; border-bottom: 1px solid var(--line);
  }
  .key-table td { padding: 10px 10px; border-bottom: 1px solid var(--line); vertical-align: middle; }
  .key-table tr:last-child td { border-bottom: none; }
  .key-label { font-weight: 600; color: var(--text); }
  .key-meta { color: var(--muted); font-size: 0.8rem; }
  .never-used { color: var(--muted); font-style: italic; font-size: 0.8rem; }
  .revoke-btn {
    background: none; border: 1px solid var(--danger);
    color: var(--danger); border-radius: 6px; padding: 4px 10px;
    font-size: 0.78rem; cursor: pointer;
  }
  .revoke-btn:hover { background: color-mix(in srgb, var(--danger) 12%, transparent); }
  .generate-form {
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 12px; padding: 18px 20px; margin-top: 16px;
  }
  .generate-form h3 { margin: 0 0 12px; font-size: 0.95rem; }
  .form-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .label-input {
    background: #0e1628; color: var(--text);
    border: 1px solid var(--line); border-radius: 8px;
    padding: 9px 12px; font-size: 0.88rem; flex: 1; min-width: 200px;
  }
  .label-input:focus { outline: none; border-color: var(--accent); }
  .gen-btn {
    background: var(--accent); color: #0b1220; border: none;
    border-radius: 8px; padding: 9px 18px; font-size: 0.88rem;
    font-weight: 700; cursor: pointer; white-space: nowrap;
  }
  .gen-btn:hover { opacity: 0.85; }
  .empty-keys {
    color: var(--muted); text-align: center; padding: 24px;
    border: 1px dashed var(--line); border-radius: 10px;
  }
"""

_INSTRUCTIONS_HTML = """
<div class="info-box">
  <h2>📱 Using API keys for programmatic access (iOS Shortcuts, scripts, CLI tools)</h2>
  <ol>
    <li>
      <strong>Generate a key</strong> using the form below. Give it a descriptive label
      (e.g. <em>"iPhone Shortcut"</em> or <em>"Home Mac CLI"</em>) so you can identify
      and revoke it later.
    </li>
    <li>
      <strong>Copy the key immediately.</strong> The full token is shown only once,
      right after you click Generate. It starts with <code>jcmcp_</code>. Once you
      navigate away, it cannot be recovered — revoke and regenerate if you lose it.
    </li>
    <li>
      <strong>Add it to your tool.</strong> Send it as a bearer token on every request:
      <br><code>Authorization: Bearer jcmcp_&lt;your-key&gt;</code>
    </li>
    <li>
      <strong>iOS Shortcut setup:</strong> open your Shortcut in the Shortcuts app,
      find the <em>Get Contents of URL</em> action, expand <em>Headers</em>,
      add a header with name <code>Authorization</code> and value
      <code>Bearer jcmcp_&lt;paste-key-here&gt;</code>.
    </li>
  </ol>
  <div class="note">
    You can generate multiple keys — one per device or script. Revoking a key
    immediately invalidates it everywhere. Your browser session (cookie) is separate
    and unaffected by key revocations.
  </div>
</div>
"""


def _key_row_html(key_id: int, label: str, created_at: str, last_used_at: str | None) -> str:
    used = f'<span class="key-meta">{last_used_at[:10]}</span>' if last_used_at else '<span class="never-used">Never</span>'
    label_display = label or "<em style='color:var(--muted)'>unlabeled</em>"
    return f"""<tr>
      <td><span class="key-label">{label_display}</span></td>
      <td><span class="key-meta">{created_at[:10]}</span></td>
      <td>{used}</td>
      <td>
        <form method="post" action="/dashboard/api-keys/{key_id}/revoke"
              onsubmit="return confirm('Revoke this key? Any tools using it will stop working immediately.')">
          <button class="revoke-btn" type="submit">Revoke</button>
        </form>
      </td>
    </tr>"""


def _build_page(user: User, new_key: str | None = None) -> str:
    keys = list_keys(user.id)

    flash_html = ""
    if new_key:
        flash_html = f"""
<div class="flash" id="new-key-flash">
  <h2>✅ New API key generated — copy it now</h2>
  <div class="warn-note">
    ⚠️ This is the only time this key will be shown. Copy it before navigating away.
    If you lose it, revoke this key and generate a new one.
  </div>
  <div class="key-display">
    <code id="new-key-val">{new_key}</code>
    <button class="copy-btn" onclick="copyKey()">Copy</button>
  </div>
  <div class="shortcut-steps">
    <strong>iOS Shortcut:</strong> Open your Shortcut → <em>Get Contents of URL</em>
    action → expand <em>Headers</em> → add header name <code>Authorization</code>,
    value <code>Bearer {new_key}</code>.<br>
    <strong>CLI / script:</strong>
    <code>curl -H "Authorization: Bearer {new_key}" https://your-host/tools/...</code>
  </div>
</div>
<script>
function copyKey() {{
  var val = document.getElementById('new-key-val').textContent;
  navigator.clipboard.writeText(val).then(function() {{
    var btn = document.querySelector('.copy-btn');
    btn.textContent = 'Copied!';
    setTimeout(function() {{ btn.textContent = 'Copy'; }}, 2000);
  }});
}}
</script>"""

    if keys:
        rows = "\n".join(_key_row_html(k.id, k.label, k.created_at, k.last_used_at) for k in keys)
        table_html = f"""
<div class="section-title">Your API keys</div>
<div class="card" style="padding:0;overflow:hidden">
  <table class="key-table">
    <thead><tr>
      <th>Label</th><th>Created</th><th>Last used</th><th></th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""
    else:
        table_html = '<div class="empty-keys">No API keys yet. Generate one below to get started.</div>'

    generate_form = """
<div class="generate-form">
  <h3>Generate a new API key</h3>
  <form method="post" action="/dashboard/api-keys">
    <div class="form-row">
      <input class="label-input" type="text" name="label"
             placeholder='Label (e.g. "iPhone Shortcut")' maxlength="80" />
      <button class="gen-btn" type="submit">Generate key</button>
    </div>
  </form>
</div>"""

    body = flash_html + _INSTRUCTIONS_HTML + table_html + generate_form
    return html_page("API Keys", "api-keys", "Manage programmatic access tokens", _EXTRA_CSS, body)


@router.get("/api-keys", include_in_schema=False)
async def api_keys_page(user: User = Depends(require_authenticated_user)) -> HTMLResponse:
    return HTMLResponse(_build_page(user))


@router.post("/api-keys", include_in_schema=False)
async def generate_api_key(
    label: str = Form(default=""),
    user: User = Depends(require_authenticated_user),
) -> HTMLResponse:
    _key_id, plaintext = create_key(oid=user.id, label=label.strip())
    return HTMLResponse(_build_page(user, new_key=plaintext))


@router.post("/api-keys/{key_id}/revoke", include_in_schema=False)
async def revoke_api_key(
    key_id: int,
    user: User = Depends(require_authenticated_user),
) -> RedirectResponse:
    revoke_key(key_id, user.id)  # oid guard: silently ignores wrong-owner attempts
    return RedirectResponse(url="/dashboard/api-keys", status_code=303)
