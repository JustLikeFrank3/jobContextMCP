# Security testing

`deploy.yml` now calls reusable security jobs for the **same commit** before any
image publish or rollout: QA requires tests + Bandit + DAST; main additionally
requires SonarCloud. Deployment checkouts use `github.sha`, not a mutable branch
tip, so badge commits cannot change the code after scanning. Failure or skipping
a required dependency prevents the corresponding deployment job. The existing
push/manual triggers still apply; this patch itself does not trigger a deployment.

PR workflows provide early feedback, while release safety does not depend on
branch-protection settings. Administrators can separately require the applicable
PR checks. No remote repository settings are changed by these files.

## SAST — SonarCloud

The existing `SonarCloud / sonar` quality gate remains the SAST engine. It covers
Python plus first-party frontend, mobile and desktop source. Generated output,
vendor dependencies and client test files are excluded. Python coverage remains
measured; client coverage is explicitly excluded until instrumented reports exist.
Rust analysis depends on the SonarCloud project's enabled language support; merely
including desktop source is not a claim that every language is analyzed.

Sonar requires the existing `SONAR_TOKEN` and project configuration. Same-repository
PRs to main, main deploy-workflow calls and main pushes touching mobile are analyzed; forks and Dependabot PRs are explicitly
skipped because they cannot safely receive that secret. The existing free-plan
branch restriction is preserved. Do not switch to `pull_request_target` to bypass
this. Scan upload alone is insufficient: `sonar.qualitygate.wait=true` is retained.
Coverage and scan-task metadata are kept for 14 days, including failed runs.

## SAST — secretless release gate

`Python SAST / Bandit` scans first-party Python on PRs to qa/main and as a reusable
prerequisite for both deployment jobs. It needs no secret and also runs for forks.
Medium/high-severity findings at medium/high confidence fail. JSON findings are
retained even on failure. No existing findings are silently baselined. This
complements Sonar rather than pretending Sonar's free-plan QA restriction does
not exist: broad client-language analysis remains a main Sonar gate, while QA's
mandatory SAST gate is Python-only.

## SCA — dependency review

`Dependency Review / dependency-review` compares dependency changes in PRs to qa
and main. Newly introduced **high/critical** advisories block; lower severities
remain visible. It needs GitHub's dependency graph/review support, but no secrets,
checkout, package execution or write permissions. This is PR-delta SCA, not a
whole-installed-graph audit: Python requirements use ranges, so resolved transitive
Python vulnerabilities may require a future lockfile + installed-environment audit.
Existing vulnerabilities and native/runtime system packages need separate review.

## DAST — ZAP against a disposable HTTP app

`DAST / ZAP disposable app` runs on qa/main PRs, manual dispatch, and as a
reusable prerequisite of both qa/main deployment jobs. It is not manual-only.
Run locally on a Linux Docker host with Python 3 and GNU `timeout`:

```sh
python3 -m unittest discover -s security/dast -p 'test_*.py' -v
security/dast/run.sh
```

This is an **active scan**, but it accepts **no URL or other arguments**. The only
target is `http://app:8000`, freshly built from this checkout. Both app and ZAP run
on a dedicated Docker `--internal` network, with no published ports, Docker socket,
host networking, production volumes or credentials. Outbound access to QA,
production, external links, identity providers and LLM services is blocked at
runtime. Package/image downloads occur before isolation. It must never be adapted
into a live-production scan by changing the URL.

The CI-only image copies source explicitly, not `data/`, local configuration or
personal workspaces. App state is empty/synthetic, writable only in disposable
tmpfs mounts; the root filesystem is read-only. Auth is enabled using a fixed,
non-secret test value, **not supplied to ZAP**. Consequently this tests public
pages, the built SPA's HTTP responses and unauthenticated API boundaries, not
logged-in tenant flows or the native mobile/desktop runtime. The traditional
spider does not execute the SPA's JavaScript. No real OAuth/LLM calls are tested.

ZAP's image is digest-pinned; update it deliberately after reviewing upstream
releases. GitHub Actions are commit-pinned. Full scanning is bounded by a 2-minute
spider, a 20-minute process timeout and a 35-minute job timeout. Execution errors,
timeouts, absent/malformed/unexpected-target reports fail closed. **Medium/high**
findings fail; low/informational findings remain in reports. There are no blanket
rule suppressions. Any future exception needs a reviewed rationale and expiry.

HTML/JSON/Markdown scan reports and app logs are uploaded for 14 days even on
failure. Cleanup removes containers, the dedicated network and local app image.
Cancellation may prevent shell cleanup; GitHub's hosted runner remains disposable.
Review artifacts as untrusted scanner output. Reports from this fixture should
contain no personal data; do not add real tokens or datasets to it.

## Rollout verification

Before calling these controls operational, run the workflows on a reviewed branch,
inspect artifacts and verify findings truly block. If current findings fail the
gate, fix or narrowly triage them rather than weakening the default threshold.
Require appropriate PR checks separately through authorized repository settings.
Sonar can be skipped for fork PRs, so it is not a universal fork SAST gate.

## Finding fixes and browser regressions

See [security-findings.md](security-findings.md) for query-by-query dispositions,
login-CSRF details, public/SPA CSP coverage and the explicitly retained legacy-HTML
source-policy limitation. No medium/high DAST exception or SAST baseline was added.
The security regression PR workflow tests the relevant Python suites, builds/tests
the SPA, and checks browser CSP/preview behavior against disposable local state.
It has no deployment credentials and does not target QA or production.
