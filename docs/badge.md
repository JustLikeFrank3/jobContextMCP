# Conference badge integration

Device setup and button reference live in [`badge/README.md`](../badge/README.md).
This is the cloud-side design: what the badge surface is, why it is separate,
and what the scoped credential model buys.

## Shape of it

```
badge (MicroPython)          cloud
─────────────────            ───────────────────────────────────
  type a company    ──GET──> /api/badge/search      → job_queue + employer_directory
  pick a result
  choose material   ─POST──> /api/badge/materials   → work.enqueue("badge_materials")
  spinner           ──GET──> /api/badge/work/{id}   ← dispatcher runs generate_*
```

Nothing about this is a new subsystem — it is the control plane
(`lib/work.py`, [control-plane.md](control-plane.md)) with a very small
read surface bolted on.

`badge_materials` is an *asynchronous orchestrator*, not a second
implementation of generation. P1 routed the generators themselves through
the control plane via the `@tracked` decorator in `tools/generate_work.py`,
which uses `run_now` — inline, because interactive callers are waiting for
the document. The badge is the case that cannot wait: it is battery powered,
on conference WiFi, and polling. So `badge_materials` is enqueued, the
dispatcher runs it in the background, and it calls the tracked generators
from there. Each document still gets its own stamped row with
`prompt_version` and `model`; the badge just gets one id to poll.

That nesting is the established shape rather than a special case —
`capture_url` has done exactly the same thing since assessment became
tracked.

## Why a separate router instead of reusing /api/work

Two reasons, both about the device rather than tidiness.

**Size.** The badge draws ~38 characters per line of small text and parses
responses with `json.loads` on a microcontroller. `/api/work/{id}` returns inputs, timings,
attempt counts and full tracebacks; `/api/badge/work/{id}` returns a status,
a list of what got made, and at most one clipped line of error. The server
truncates to display width so the firmware carries no layout logic.

**Blast radius.** The badge's credential is semi-public (see below), so the
surface it can reach should be the smallest thing that does the job, not a
general-purpose API that merely happens to be what the badge calls today.

## Scoped API keys

`user_api_keys` grew a `scope` column: `full` (everything, the historical
behaviour and the default) or `badge` (`/api/badge/*` only).

The threat is unglamorous and real: double-tapping reset on a Universe badge
mounts it as a USB mass-storage device, and `secrets.py` sits there in plain
text. A badge is a thing you hand to strangers, leave on a table, and lose. A
full PAT on one is a full compromise of the job search it belongs to; a badge
token buys an attacker a search box and the ability to queue you a resume.

### Where it is enforced

In `UserDataContextMiddleware` (`transport/http/app.py`), before any partition
is entered — **not** only in route dependencies. The MCP mount never evaluates
FastAPI dependencies, so a check that lives only in `require_authenticated_user`
would leave every MCP tool reachable by a badge key. The middleware is the one
place that sees both the resolved identity and the request path for every
request, so that is where `scope_permits()` is called.

`require_authenticated_user` *also* rejects non-full scopes, as defence in
depth and for tests that exercise routes directly. `require_badge_client` is
the only dependency that accepts a badge key, and full credentials pass it too
so curl and the dashboard can drive the same endpoints.

A scoped refusal is **403, never 401**. The token is authentic; telling the
badge to re-authenticate would send it round a loop it cannot win. This is the
same reasoning as the `AuthUnavailable` → 503 rule in `lib/auth.py`: never
answer "you are not who you say" when the truth is "you may not do that".

### Migration note

The `scope` column is added by `_ensure_scope_column()` in `lib/api_keys.py`,
not by the `_MIGRATIONS` list. `_apply_migrations` skips every statement
containing `ALTER TABLE` when running against the global DB — it assumes such
statements target per-user tables like `job_queue` — and `user_api_keys` is
global. A migration-list entry would have been ledgered as applied without
ever running. Rows written before the column existed read back as `full`, so
existing keys keep exactly the reach they already had.

## Search behaviour

`/api/badge/search` matches company *or* role across `job_queue`, then tops up
from `employer_directory` for companies that are known but not yet queued.
Directory hits carry `job_id: 0`, which the firmware treats as "nothing to
generate against yet" — generating from one would produce a resume tailored to
an empty job description.

## Input, and the Bluetooth keyboard

Text entry is a grid keyboard on the Universe 2026 badge's capacitive d-pad:
SELECT presses a key, BACK deletes, MENU searches. (The first version targeted
the 2025 badge, which had only UP/DOWN/A/B/C, and used a one-dimensional
character carousel for want of left/right.)

On a badge with physical buttons instead — a stock Tufty 2350 or the 2025
badge on current firmware — `ui.py` maps the same logical actions: A/C are
LEFT/RIGHT, a tap of B is SELECT and a long press of B is BACK. That keeps a
single app testable on hardware you can buy before the conference.

The original ask was a paired Bluetooth keyboard. It is scaffolded but not
implemented, because it requires the badge to be an HID-over-GATT *host* and
MicroPython's entire BLE HID ecosystem is peripheral-side — libraries for
pretending to *be* a keyboard, not to read one. `badge/README.md` has the full
reasoning and two cheaper alternatives. `inputs.py` defines the source
interface so this can land without touching the state machine.

## Tests

- `tests/test_badge_api.py` — scope containment (proved by contrast: each
  blocked path is shown to serve a full key first), search shape, enqueue and
  poll, and that the poll never returns a traceback.
- `tests/test_badge_firmware.py` — the real app modules (state machine, ui,
  api, keyboard, inputs) against a fake Universe 2026 runtime: text entry and
  hold-to-repeat, deferred network calls (the status frame is presented
  before the call blocks), polling cadence, HTTP error mapping, and the
  press-leak regression (the SELECT that opens the actions menu must not also
  press "generate").
- `badge/simulator/` — not a test suite but a renderer: every screen through
  Pimoroni's Badgeware simulator, which is where the text layout was measured.
- `tests/test_api_keys.py::TestKeyScopes` — scope storage and resolution,
  including pre-scope rows reading as `full`.
