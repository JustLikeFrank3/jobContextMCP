# Native Alexa+ integration status

Checked September 6, 2026. Production remains frozen. This document is not a
claim that the legacy custom skill is a native Alexa+ add-on.

## Onboarding blocker

The signed-in developer account's native add-ons console at
https://developer.amazon.com/alexa/console/ask/addons shows **Coming Soon**.
No Alexa AI CLI or AWS CLI was found on the current Windows host. Only
docker-desktop is registered with WSL; Amazon documents macOS/Ubuntu and Node 24+.

Amazon's published setup obtains `@alexa-ai/cli` from a private CodeArtifact
repository by assuming Amazon's `AddOn3PDeveloperToolsRead` role. Access has
not been confirmed. Do not invent access, install an unrelated similarly named
package, or claim a successful native deployment based on the legacy simulator.

## Reusable implementation

`interviews/prepare` resolves a saved company/role, rejects ambiguous matches,
queues `generate.interview_prep` and returns a work ID quickly. Poll
`documents/generation_status`; `interviews/read_prepared` reads the latest saved
result for that role. These actions use the existing Streamable HTTP MCP facade,
so native Alexa+ can discover them once onboarded. No Coca-Cola logic is embedded.

The legacy Alexa adapter is a separate consumer: confirmed generation, compact
summary, five section headings on Echo Show and paginated spoken practice.
Its APL display is not an MCP App and must not be advertised as a native visual.

## Compatibility gaps to verify before onboarding

Run `python scripts/check_alexa_plus.py https://qa.jobcontext.ai/mcp` for public
discovery checks. It does not authenticate or certify the integration.

- Amazon currently documents no `WWW-Authenticate` on 401 responses; the shared
  MCP endpoint deliberately sends a standards-based challenge. Do not remove it
  globally and break existing clients. Confirm an isolated compatibility endpoint
  or supported Amazon configuration before implementing an exception.
- Amazon documents service-level client credentials for initialize/tools/list,
  separate from user-level authorization-code PKCE for personal tools. Existing
  user tokens must never be repurposed as service credentials. No workspace access
  may be granted to a service token.
- Native onboarding does not support DCR or OIDC. Configure a static client and
  compatible scopes through the approved account-linking path; keep existing MCP
  client behavior intact.
- Reconcile the canonical resource URI with the advertised origin and registered
  resource. Test access-token expiry, refresh, invalid resource and cross-tenant
  denial. PKCE S256 must remain required.
- Measure authenticated queries against the documented sub-500ms round-trip
  target. Background generation avoids holding a tool call for an LLM, but reads
  and metadata also need measurements. Do not report network-wide latency from a
  unit test.
- Build native visuals with MCP Apps, then test with Amazon's local inspector,
  native web simulator and physical-device routing.
- Redeploy the native add-on after tool/schema changes: Amazon caches discovery
  until deployment.

## Planned listing

Name: jobContext QA. Endpoint: https://qa.jobcontext.ai/mcp (subject to the
authentication compatibility decision above). English (US), US development use.

Short description: Prepare for interviews and manage your job search with context from your own workspace.

Example phrases: Prepare for my interview at Coca-Cola; Which jobs are in my
pipeline?; Show my saved job boards; Read my interview prep.

Native package remains unsubmitted. Before creating a deployable manifest,
verify privacy/terms URLs and supply the six required light icon sizes plus a
600x900 carousel image. Do not insert fictional public asset URLs.

## Official references

- [MCP quickstart](https://www.developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html)
- [Development environment](https://www.developer.amazon.com/docs/alexaplus/add-ons/set-up-your-development-environment.html)
- [Authentication](https://www.developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-authentication.html)
- [Account linking](https://www.developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-account-linking.html)
- [Testing and physical-device routing](https://www.developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-test-add-ons.html)
