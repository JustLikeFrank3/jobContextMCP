# Authenticated and tenant-isolation assurance matrix

This matrix maps selected security requirements to repository evidence. It is
an engineering checklist, not a penetration-test result, compliance claim, or
proof that every route is isolated. Tests use synthetic identities and data;
real identity-provider and production behavior are outside their scope.

## Current evidence

| Requirement | Current automated evidence | Boundary / remaining evidence |
| --- | --- | --- |
| An authenticated HTTP identity resolves to its own data partition | `tests/test_entra_auth.py::TestUserDataContextMiddleware::test_routes_authenticated_user_to_user_partition`; `test_two_authenticated_users_see_only_their_own_materials` | Synthetic auth provider; the two-user test covers materials listing, work-item read (owner succeeds, other user gets 404), and tenant-specific work stats. Inventory other tenant-bearing routes and assert read/write isolation for each resource family. |
| An unscoped administrator credential cannot read tenant data | `tests/test_entra_auth.py::TestUserDataContextMiddleware::test_admin_api_key_session_cannot_access_tenant_data` | Covers the tested materials route and response; does not establish a complete role/action matrix. |
| A background executor uses the partition recorded on its work row | `tests/test_work.py::test_execute_runs_in_the_rows_partition` | Exercises the control-plane executor contract with a synthetic partition. Add route-level cross-user assertions for reading or mutating another user's work item. |
| Context survives the consolidated async worker-thread hop | `tests/test_consolidated_async_dispatch.py::TestContextvarsSurviveTheThreadHop::test_partition_context_visible_inside_worker_thread` | Verifies context values reach one stubbed action; does not prove every tool's data access or authorization policy. |
| Owner contact details do not fall back into an unconfigured user partition | `tests/test_contact_isolation.py::TestContactIsolation` | Focused configuration-resolution tests, not coverage of all generated/exported content or file stores. |
| SQL input remains data at reviewed query boundaries | `tests/test_sql_security.py` | Targeted SQL regression set; not a general authorization or tenant-isolation proof. |
| Public HTTP and selected browser security behavior | `.github/workflows/security-regressions.yml`; `docs/security-testing.md` | ZAP is unauthenticated and the traditional spider does not execute SPA JavaScript. Browser tests are selected synthetic regressions, not exhaustive route/client coverage. |
| Restricted badge credential stays within its exact API path segment | `tests/test_badge_api.py::test_badge_scope_does_not_match_sibling_path_prefixes`; `scope_permits()` in `transport/http/security.py` | Review found raw `startswith("/api/badge")` also permitted sibling prefixes such as `/api/badge-admin`. Matching now requires the exact prefix or a slash boundary. No current sibling endpoint was identified; this is a fixed authorization-policy gap, not a confirmed data exposure. |
| Verified Entra token has a stable tenant owner key | `tests/test_entra_auth.py::TestEntraAuthProvider::test_missing_stable_identity_claim_is_rejected` | Review found missing `oid` and `sub` claims fell back to the shared `unknown` partition. The provider now rejects tokens without a non-empty string identity. Tests simulate decoded claims; they do not contact Entra. |
| Entra JWT is bound to the configured directory | `tests/test_entra_auth.py::TestValidateToken::test_foreign_tenant_raises`; `test_missing_tenant_claim_raises` | Review found issuer validation was disabled for v1/v2 compatibility without a separate `tid` check. Validation now requires the signed `tid` to match `ENTRA_TENANT_ID`. Synthetic JWT tests verify rejection; no live identity provider was contacted. |

The secretless security-regression workflow runs the auth and work-context
tests above on pull requests to `qa` and `main`. The complete test suite also
runs as part of deployment checks. Passing either workflow is evidence for its
tested assertions and commit only.

## Evidence still needed

Before making a broader authenticated-assurance claim, maintain a versioned
inventory with one row per resource/action family:

| Resource/action family | Owner identity source | Read isolation test | Write isolation test | Background/export/sync paths | Status / reviewer |
| --- | --- | --- | --- | --- | --- |
| Dashboard files and generated materials | Synthetic authenticated user | TODO | TODO | TODO | Not assessed as a complete family |
| Work items and artifacts | Work-row partition | Cross-user GET `/api/work/{id}` returns 404; stats omit another user's kind (`test_two_authenticated_users_see_only_their_own_materials`) | TODO | Executor partition test exists; no mutation API in this surface | Partial |
| Job pipeline, contacts, and evaluations | Authenticated user partition | TODO | TODO | TODO | Not assessed as a complete family |
| Sync, import/export, backups, and restore | Authenticated user partition | TODO | TODO | TODO | Not assessed as a complete family |
| MCP and consolidated tool actions | Authenticated request context | TODO | TODO | Worker-thread context test exists; per-action authorization coverage TODO | Partial |

Replace each `TODO` with a test or reviewed evidence reference, or record why
the operation is not applicable. A useful cross-tenant test uses two distinct
synthetic users in the same app instance, attempts both read and mutation
operations against the other user's identifiers, and verifies there is no data
change or disclosure. Include object-level work-item access and background
execution, not only path selection.

Additional evidence boundaries to retain in release records:

- Synthetic middleware tests do not exercise Entra's live identity-provider
  behavior, account lifecycle, or production ingress configuration.
- ZAP's disposable scan does not authenticate and is not an authenticated
  tenant scan. Do not repoint it at QA or production.
- Browser smoke checks do not establish native desktop/mobile runtime behavior
  or complete MCP client authorization coverage.
- Tie every claimed result to the exact commit, workflow run, retained artifact,
  skipped checks, and reviewed exceptions. Do not carry a prior commit's result
  forward as evidence for a newer release.

Any active assessment requires a separately approved scope, synthetic data,
isolated owner-controlled environment, and stop conditions. This document does
not itself authorize scanning or testing against a live service.