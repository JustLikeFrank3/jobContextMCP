# Initial Python SAST triage

Bandit 1.9.4, medium/high severity and confidence, initially reported 16 findings
across 38,547 scanned lines with zero parser errors. These are **scanner findings,
not 16 confirmed vulnerabilities**. No broad ignore list or baseline was added.
The gate intentionally blocks while findings remain unresolved.

| Rule / locations at initial scan | Initial assessment | Disposition |
| --- | --- | --- |
| B608 `lib/io_sqlite.py:708,712` | `_prune_stale` receives literal table/column names at its only call sites; row IDs are bound parameters. Likely false positives. | Keep findings until explicit reviewed narrow annotation or hardening. |
| B608 `lib/sync.py:191,265,288,299,410,432,439,449,462,465` | SQL identifiers derive from fixed `TABLE_SPECS`; values are bound parameters. Incoming row keys are filtered against schema columns before insertion. Likely false positives under the present call graph/schema ownership. | Keep findings; review identifier invariants and adversarial sync tests before suppression. |
| B608 `tools/certification.py:541` | Columns come from a local fixed tuple; values are bound separately. Likely false positive. | Keep finding pending narrow reviewed disposition. |
| B324 `evals/tenant.py:395`, `tools/certification.py:216` | SHA1 is used for stable short record IDs, not passwords, authentication or integrity verification. Changing hash algorithms would change persisted IDs. | Explicit `usedforsecurity=False` preserves output and states the non-security purpose. |
| B310 `evals/push.py:38` | Caller supplies destination URL; comment assumes HTTP(S) but code does not enforce a scheme. This is a CLI/eval helper, not by itself proof of a remotely exploitable issue. | Needs explicit scheme/redirect policy review and tests; do not suppress as proven safe. |

The two non-security hash annotations remove B324 without changing hashes.
The other 14 findings remain blocking. No production testing was performed, and
these observations are source review, not exploitation or comprehensive audit.
