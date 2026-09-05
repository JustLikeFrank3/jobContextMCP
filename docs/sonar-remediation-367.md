# Sonar gate remediation in PR #367

The manually dispatched scan evaluates the project against its existing
previous-version baseline (June 20), so it includes findings from before this
PR. Coverage and duplication passed; security and reliability blocked the gate.

Changes address the findings without changing the quality gate or adding rule
exclusions:

| Finding | Resolution |
| --- | --- |
| Alexa certificate request, S5144 | Normalize and validate the certificate path, reconstruct a fixed Amazon HTTPS origin, reject credentials/parameters/encoded paths, and explicitly disable redirects. Chain trust and SAN verification remain required. |
| Alexa SHA-1 fallback, S4790 | Require `Signature-256`, following [Amazon's current verification guidance](https://developer.amazon.com/en-US/docs/alexa/custom-skills/host-a-custom-skill-as-a-web-service.html). Legacy-only requests receive 400. |
| Materials copy, S2083 | Separate file opening from copying content; exclusively create the destination to reject overwrite races and dangling symlinks. Existing source containment and master-resume guards remain enforced. |
| Eval JSON write, S2083 | Open the server-selected path separately from serializing user content. Also validate golden-entry IDs and resolved JD paths before create/delete, closing an actual traversal path found during review. |
| Eval logs, S5145 | Log fixed event names and numeric lengths; do not interpolate user-supplied strings. Validation errors still return to the caller as JSON. |
| Eval page, S5131 | Remove the unused `updated_at` value from inline JavaScript. Move claim metadata into an escaped HTML data attribute, decoded with `JSON.parse` at runtime. User data is no longer interpolated into executable scripts. |
| Metrics, S1764 / S2583 | Use `math.isnan` instead of comparing a value with itself; preserve Prometheus `NaN` and infinity output. |
| Hash tests, S5863 | Assert known digest values, protecting persisted identifiers against accidental algorithm changes. |
| Certification regex, S5850 | Group each alternative explicitly, preserving the start anchor for “Unknown (agency client)” and unanchored “(via agency)” matching. |

Regression tests exercise traversal IDs, escaping symlinks, stored script
injection, log injection, certificate canonicalization and rejected URL forms,
legacy-only signatures, and exclusive material-copy races. Existing tests
exercise trusted signatures, tenant routing, eval persistence, and certification
matching. The scan workflow now waits for the quality gate so an upload alone
cannot leave the workflow green while the separate Sonar check is red.
The scanner action is updated from unsupported v5 to v8.2.1, and material
copying runs through AnyIO's context-preserving thread helper so synchronous
file I/O does not block the async route.
