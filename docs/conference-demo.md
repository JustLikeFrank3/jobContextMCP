# GitHub Universe: phone / laptop fallback

## Release status — October 26, 2026

The fallback is implemented on `feat/conference-demo`, based on `qa`.
It is **not deployed yet**. Publication was subsequently authorized for handoff
to Dot; no QA merge or production promotion has been attempted here. Recheck
the live environment and other pending branches before completing the release.

Existing release evidence:

- QA commit `b3acd98a3e8fdcb8dba7f1d8ebd244229a2e653e` passed tests, Bandit,
  disposable-app ZAP, image build and AKS rollout:
  https://github.com/JustLikeFrank3/jobContextMCP/actions/runs/40244728898
- Main release `21a418c404cd753569fe6675bfee443ee3b0bc9e` (PR #398) passed
  tests, Bandit and ZAP, but failed Sonar's quality gate. Its production build
  and deployment were skipped:
  https://github.com/JustLikeFrank3/jobContextMCP/actions/runs/40246040884
- Both environments answered `/health` and `/ready` with HTTP 200. Anonymous
  `/api/badge/ping` and `/api/dashboard/me` returned HTTP 401. This proves
  availability and authentication refusal, **not authenticated route
  functionality or a successful production release**.
- QA's connected workspace check confirmed the master resume and server-level
  Foundry generation configuration. The browser requires Microsoft sign-in;
  an authenticated browser rehearsal is still required.
- A real QA resume submission (work **#705**, company
  **Conference Demo QA 2026-10-26**, role **Platform Engineer — synthetic test**)
  reached the provider but returned `401 PermissionDenied: Principal does not
  have access to API/Operation.` It returned a context package rather than a
  generated resume. **QA generation is currently blocked by provider
  authorization.** This was a connector generation check, not a browser or
  badge-route end-to-end test. A cover-letter submission was separately
  blocked by automatic approval review over private master-resume use and was
  not executed. The synthetic QA application record remains clearly labeled.
- Local validation passed: **104 frontend tests**, Vite production build,
  targeted ESLint, and **132 backend/security/badge tests**. Browser smoke
  coverage was added to CI; check the published PR for its current result.

Do not merge to main or claim the fallback is conference-ready until the
QA rehearsal below passes. Keep the production quality gates enabled.

## Why a small additional screen was needed

The existing Pipeline screen filters and selects saved jobs, accepts a pasted
job description, and generates resumes and cover letters. Materials already
previews and downloads those files. However, Pipeline has no open-position
discovery interface and its generation requests wait synchronously.

The new screen lives inside the existing authenticated dashboard shell. It
reuses the existing badge discovery and background-generation routes and
links to Pipeline and Materials. There is no new backend, credential store,
service worker, public demo tenant, or change to the badge firmware/API.

## Launch after QA deployment

1. On the phone or laptop, open
   `https://qa.jobcontext.ai/app/conference-demo` and complete the normal
   Microsoft sign-in. The page must say **Conference demo**; if it shows Home,
   the new frontend is not deployed. QA has its own data and session.
2. After a separately verified production promotion, the production address
   is `https://app.jobcontext.ai/app/conference-demo`. Use the environment
   that passed rehearsal. Do not assume QA-generated files exist in prod.
3. Bookmark the tested address. On iPhone, optionally use Safari's Share →
   Add to Home Screen as a shortcut. This does **not** enable offline use.
4. Keep the device signed in and under your control. Attendees do not need
   your login or an API key. Avoid projecting account settings or private
   pipeline details unrelated to the demo.

## The live demonstration

1. Under **Search in**, choose **My pipeline** for a rehearsed saved job or
   **Open positions** for a new employer/role.
2. Enter a company or role and tap **Search**. The screen shows at most 12
   results. Narrow the search if necessary. Open-position searches require
   the server's configured search provider and obey its per-user daily cap.
3. Tap **Select** for an existing job, or **Add & select** for a discovered
   opening. Only the latter adds a job; it does not apply or send anything.
   Employer-directory-only matches cannot generate documents.
4. Check the selected company, role and job ID. The compact badge API clips
   long titles: use **Pipeline** to inspect the full role/JD if ambiguous.
5. Choose **Resume + cover letter**, **Resume only**, or **Cover letter only**.
   Tap **Generate documents** once. Generation uses the server's saved master
   resume and existing generator; no API key is pasted into this screen.
6. Keep the displayed generation number. The URL gains `?work=<number>` and
   can be bookmarked. Work continues server-side if this page closes.
7. When complete, tap **Open Materials to preview or download**, find the
   company/role, and open the newly generated resume and letter. Review
   generated content and provenance before sharing it as an application.

## Prepare the offline escape route before leaving

- Complete one real rehearsal in the selected environment on both devices.
- In Materials, download the successful resume and cover-letter PDFs. On
  iPhone, use the file/share controls to **Save to Files → On My iPhone**;
  on the laptop, save both to an easy-to-find local folder.
- Open both files with airplane mode enabled to verify that their bytes are
  actually on the device. A browser bookmark or cloud-only file is insufficient.
- Save a short screen recording of the successful flow if useful. Label
  prerecorded or synthetic examples honestly when showing them.
- Keep the iPhone hotspot ready. Sign in before entering the conference
  venue; avoid spending the demonstration on the login flow.

## Recovery at the conference

| Situation | Action |
| --- | --- |
| Venue Wi-Fi unavailable | Switch the phone to cellular; connect the laptop to the phone hotspot. Keep the page open. Offline mode disables new submissions. |
| No usable network at all | Show the locally saved PDFs/recording and say they are a previous run. New search/generation requires the server; the browser is not an offline app. |
| Connection drops after Generate | Do not tap Generate again. Reconnect, choose **Check status**, or reopen the saved `?work=` URL. |
| Generate response is lost before a work ID appears | **Refresh recent generations**, select the newest matching job/run and inspect Materials. The screen blocks another generation until this check is acknowledged. Never automatically repeat the POST. |
| Page refreshes or phone suspends it | Reopen the same URL, or use **Recent generations → View status #…**. The list covers badge/conference runs among the latest 50 work items. |
| Status polling fails | The page keeps the work ID and pauses polling. Restore connectivity, then **Check status**. This only reads status. |
| Session expires | Use **Sign in in another tab**, complete Microsoft sign-in, return to the original tab and check status. No credentials need to be copied. |
| Search fails, is unconfigured or hits its cap | Use **My pipeline** and a rehearsed job. Alternatively use Pipeline's **Add Job** with the full JD. |
| Search results expire | Search again, then select a fresh result. |
| Generation fails | Check Materials first. Select and generate only the failed document once after addressing the cause. If it still fails, show the saved example. |
| One of two documents completes | The page says **Partially completed** and names the missing document. Keep the successful file; retry only the missing document. |
| Generation stays queued/running for several minutes | Show the saved example while retaining the work ID. Check status later; don't pile up duplicate work. A server restart is handled by the existing control plane, not by the browser. |
| New screen unavailable | Existing fallback: `/app/pipeline` → filter/select or **Add Job** → generate resume and letter separately → `/app/materials`. Generation there is synchronous; after a timeout, inspect Materials before retrying. |

## Authentication and endpoint contract

Every request stays on the dashboard's origin using its existing HttpOnly
`jc_session` cookie. No credentials appear in source, client assets, query
strings or browser storage. The query-string work ID is an identifier only;
the backend still scopes reads to the authenticated tenant.

| Endpoint | Used for |
| --- | --- |
| `GET /api/dashboard/me` | Existing dashboard session gate |
| `GET /api/badge/search?q=…&limit=12` | Existing pipeline and directory search |
| `GET /api/badge/jobs?q=…&limit=12` | Open-role discovery |
| `POST /api/badge/jobs/queue` | Explicit selection of discovered job |
| `POST /api/badge/materials` | Queue generation and obtain a work ID |
| `GET /api/badge/work/{id}` | Compact generation polling |
| `GET /api/work?limit=50`, `GET /api/work/{id}` | Authenticated recovery after refresh/lost response |
| Existing Materials routes | Preview/download generated files |

Badge-scoped keys still cannot access `/api/work`, Materials or the dashboard.
The fallback uses a normal full dashboard session; it does not widen badge
permissions or expose an anonymous demo mode.

## Required QA rehearsal and promotion

1. Publish the feature branch and open a PR targeting `qa`. Wait for the PR
   security, frontend, browser-smoke and DAST checks. Merge to QA and verify
   the exact merge SHA's test, image-build and AKS rollout jobs succeed.
2. Sign in at the QA fallback URL. Run a pipeline search, select a job and
   generate both documents. Observe server completion, open both files in
   Materials and confirm their contents belong to the signed-in account.
3. Run one bounded open-position search. **Add & select** one result and
   verify the existing Pipeline row contains its real JD. Re-selecting the
   same stored result must not duplicate the job.
4. Start a generation, refresh the page, then verify the same work ID resumes.
   Briefly disconnect the client network; reconnect and use **Check status**.
   A lost client connection must not cause another generation POST.
5. Confirm expired sessions request sign-in and another account cannot read
   the first account's work/materials. Existing automated regressions cover
   these boundaries; do not disable auth for a live rehearsal.
6. Verify the screen at a phone width (390px) and laptop width (1440px),
   including navigation, touch targets and Materials access.
7. Only after this passes, open a `qa → main` promotion PR. Resolve the
   existing Sonar failure without bypassing the gate. Verify production's
   exact SHA deployment, then repeat the bounded authenticated smoke there.

Local regression commands:

```bash
npm ci --ignore-scripts --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
LLM_PROVIDER=foundry python -m pytest tests/test_badge_api.py \
  tests/test_badge_firmware.py tests/test_webmcp_csrf.py \
  tests/test_dashboard_login_csrf.py -q
```

The existing Security regressions workflow now also tests the built screen
at 390px/1440px with real authenticated local routes and a synthetic offline
executor. Its screenshots are `conference-390.png` and
`conference-1440.png` in the `security-browser-*` workflow artifact. This
checks browser integration; it does not replace the live QA rehearsal.
