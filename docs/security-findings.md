# Security scan finding dispositions

The original Bandit 1.9.4 scan reported 16 findings (38,547 lines, zero parse
errors). Two non-security SHA1 identifier uses were already marked
`usedforsecurity=False`, preserving persisted IDs. The remaining **14 findings**
and the first completed disposable ZAP report were reviewed below. Scanner
findings are not automatically confirmed vulnerabilities.

## Python SAST

| Original rule / locations | Review and disposition | Regression evidence |
| --- | --- | --- |
| B608 `lib/io_sqlite.py:708,712` | `_prune_stale` previously interpolated literal caller identifiers. It now accepts only two explicit table/column pairs and executes literal SQL; unsupported pairs fail before SQL execution. Row IDs remain bound. | `tests/test_sql_security.py`: hostile identifiers rejected, hostile IDs stay data, valid pruning still works. |
| B608 `lib/sync.py:191,265,288,299,410,432,439,449,462,465` | Ten false positives narrowly annotated `nosec B608` at the query, with provenance. Peer table names resolve through the fixed `TABLE_SPECS` registry; insert keys are filtered against the locally owned schema; natural keys, timestamps and row values are bound. Triggers/backfill use only registry identifiers and local SQL literals. No peer-provided schema or `TableSpec` is accepted. | Adversarial table/key/value cases, export/backfill, append deduplication, parent-FK mapping, manual-override and delete behavior in `tests/test_sql_security.py`; existing sync suite retained. |
| B608 `tools/certification.py:541` | One false positive narrowly annotated: columns come from the immediately preceding fixed tuple, never caller keys; values use placeholders. | Hostile employer names/values and extra caller keys cannot become SQL syntax. |
| B310 `evals/push.py:38` | Warranted hardening. Only explicit absolute HTTP(S) URLs are accepted; userinfo, query/fragment ambiguity, controls, backslashes and malformed ports are rejected. All redirects fail, even same-origin redirects, so bearer credentials and evaluation data never follow a `Location`. HTTP loopback desktop endpoints and base-path prefixes remain supported. No B310 suppression. | `tests/test_eval_push_security.py`: valid JSON/auth/error behavior and disposable loopback 301/302/303/307/308 tests prove the redirect destination receives nothing. |

No blanket skip, baseline, severity reduction or confidence reduction was added.
The eleven B608 exceptions depend on the documented registry/schema ownership;
changes to those trust boundaries require re-review.

## DAST: original report `40005192443`, head `6d38016`

The completed active scan visited 18 URLs on its synthetic internal Docker target.
The four medium alert classes were real missing controls on that HTTP surface:

| ZAP rule | Evidence | Fix |
| --- | --- | --- |
| 10202, absent anti-CSRF token | `/dashboard/login?next=%2Fapp`, API-key login POST form | Hidden random challenge + HttpOnly pre-login cookie, constant-time match and same-origin browser provenance required **before** credential authentication. HTTPS uses a Secure `__Host-` cookie; local HTTP is supported. Challenge pages are `no-store`; successful login clears the challenge. Entra PKCE/callback and auth-disabled flows remain separate. |
| 10038, missing CSP | Public marketing/login pages | Strict public-page policies with `default-src 'none'`, self-only scripts, explicit resource origins, and hashes of **source-controlled template** CSS blocks, never hashes of rendered/request content. Authored style attributes were migrated to CSS classes; neither `unsafe-hashes` nor `unsafe-inline` is permitted. Scripts never allow inline handlers or eval. The SPA uses same-origin fonts/scripts/styles; preview popup assets were externalized to preserve printing and rendering. |
| 10020, missing anti-clickjacking header | Public HTML | App-boundary `frame-ancestors 'self'` + `X-Frame-Options: SAMEORIGIN`, including auth errors and static content. Same-origin document/template preview iframes continue to work. `nosniff` and a referrer policy were also added. |
| 90003, missing SRI | `/architecture`, external Mermaid 11.4.1 script | Removed the runtime executable dependency entirely: two maintained inert, same-origin SVG diagrams preserve the content. The SPA's variable third-party font stylesheet was also replaced with licensed, hash-documented local assets instead of trying to integrity-pin user-agent-dependent CSS. |

### Scope and compatibility limits

The follow-up disposable scan `40127807506` visited 23 URLs and cleared all four
original classes. It identified medium rule 10055 (`style-src unsafe-hashes`),
which was addressed by moving the fixed public-template style attributes into
class rules and removing that CSP allowance, not suppressing the alert. The
next disposable scan `40128763231` passed with only informational alerts. The
real-browser runs also exposed a [confirmed Playwright Chromium routing defect](https://github.com/microsoft/playwright/issues/43496):
request interception stalls subresources in `about:blank`/`document.write`
popups. The browser fixture uses a fail-closed loopback allowlisting proxy rather
than Playwright HTTP interception, retaining external-request blocking and the
same style/print assertions. Popup URLs are explicitly resolved against the
parent application's origin, but that alone did not fix the test-tool defect.

- Strict source CSP covers the reviewed public templates, API-key login/callback
  pages, logged-out page and React SPA. Other routes, including OAuth consent,
  QA-only discovery and authenticated legacy dashboard/generated-document HTML
  still has inline handlers/styles and receives **only base/object/framing CSP**,
  not comprehensive script/style restrictions. This is deliberate compatibility
  debt, not a claim that legacy XSS is solved or an ignored ZAP alert. A separate
  authenticated scan and migration are needed before applying strict source CSP
  there. OAuth consent/external-client redirects are not restricted by a global
  `form-action 'self'` policy.
- API-key form login requires same-origin Origin/Referer or Fetch Metadata;
  direct clients should continue authenticating with bearer headers. The ingress
  must preserve the external Host and supply the correct single
  X-Forwarded-Proto, as the existing secure-cookie code already expects. No
  client-supplied X-Forwarded-Host trust was added.
- Unhandled server errors and CORS short-circuits can bypass the application
  middleware; handled auth failures and static/normal route responses receive
  the headers. This does not claim ingress-level coverage.
- Public templates still load Google Fonts through explicit style/font origins;
  these are not executable scripts. The React SPA's fonts are fully local.
- DAST remains unauthenticated, disposable and network-isolated. It is not an
  authenticated tenant, native-client, ingress or whole-application certification.
  The scanner never targets live QA/production, changes branch protection or
  deploys. ZAP medium/high alerts still fail without exceptions.

## Validation

Focused regression tests cover SQL injection boundaries, outbound redirects,
login CSRF, Entra/OAuth/WebMCP behavior, CSP headers/hash provenance, inert diagrams
and SPA preview/print behavior. The PR records the exact final SHA, local test
results and CI links. Browser enforcement is checked by the secretless security
regression workflow against a fresh local synthetic app, never a live service.
