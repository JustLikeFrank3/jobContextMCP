# Local k3d cluster

Run the real jcmcp container in a real Kubernetes cluster on your machine —
the layer qa currently tests for us (manifests, env wiring, frozen-container
behavior, probes) without a push-wait-check loop.

Not a replacement for `uvicorn` when iterating on Python code (that's still
faster), and it does **not** rehearse the Azure glue: workload identity,
Blob seed/sync, cert-manager, and the nginx ingress are all absent locally.

## Prerequisites

- Docker (daemon running)
- kubectl
- [k3d](https://k3d.io/#installation) — single static binary:
  `curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash`

## Quickstart

```bash
./scripts/local-cluster.sh up      # create cluster, build image, deploy (~2-3 min cold)
# → http://localhost:8080

./scripts/local-cluster.sh rebuild # after code changes: rebuild image + restart pod
./scripts/local-cluster.sh apply   # after manifest/.env.local changes (no image build)
./scripts/local-cluster.sh logs    # follow app logs
./scripts/local-cluster.sh status  # pods/svc/pvc
./scripts/local-cluster.sh down    # delete cluster + all its data
```

With no `.env.local`, the app runs with **auth disabled** (API-key provider,
no key set) and no LLM provider — enough to smoke-test boot, dashboard,
`/health`, `/metrics`. Copy `.env.local.example` to `.env.local` to configure.

## kubectl context safety

The script creates a `k3d-jcmcp-local` context but **never activates it** —
your current context (AKS prod!) stays current. Reach the local cluster with:

```bash
kubectl --context k3d-jcmcp-local -n jcmcp-local get pods
```

## Real Entra sign-in locally

Entra exempts `http://localhost` from its HTTPS redirect-URI requirement, so
the local cluster does real Entra auth — same tenant, real tokens, real OIDs.
Use a **separate dev app registration** so prod's registration and secret
stay untouched:

1. Azure portal → Microsoft Entra ID → App registrations → **New registration**
   - Name: `jcmcp-local-dev`
   - Supported account types: match the prod registration
   - Redirect URI (Web): `http://localhost:8080/dashboard/callback`
2. Certificates & secrets → **New client secret** → copy the value
3. Fill in `.env.local`:
   - `LOCAL_ENTRA_TENANT_ID` — Directory (tenant) ID from the Overview page
   - `LOCAL_ENTRA_CLIENT_ID` — Application (client) ID
   - `LOCAL_ENTRA_CLIENT_SECRET` — the secret value from step 2
   - `LOCAL_ENTRA_OWNER_OID` — your user's Object ID (Entra → Users → you)
4. `./scripts/local-cluster.sh apply`

## How it maps to qa/prod

| Piece | qa/prod (AKS) | local (k3d) |
|---|---|---|
| Image | ACR, pushed by CI | `docker build` + `k3d image import` |
| Data seed/backup | Blob initContainer + 15-min sync sidecar | none — local-path PVC only |
| Identity to Azure | workload identity SA | none |
| Storage class | managed-premium / managed-csi | local-path |
| TLS + ingress | cert-manager + nginx | none — ServiceLB → `localhost:8080` |
| Entra redirect | `https://app.jobcontext.ai/...` | `http://localhost:8080/...` (dev app reg) |

Keep `k8s/local/deployment.yaml` a minimal diff against `k8s/qa/deployment.yaml`
— when the qa manifest changes, mirror it here (minus the Azure glue) so the
overlay doesn't drift.

## Troubleshooting

- **Port 8080 busy** — edit `HOST_PORT` in `scripts/local-cluster.sh`, then
  `down` + `up` (the mapping is fixed at cluster create). Update the dev app
  registration's redirect URI and `SERVER_BASE_URL` in
  `k8s/local/deployment.yaml` to match.
- **Pod stuck ImagePullBackOff** — the image import didn't happen or the tag
  changed; run `./scripts/local-cluster.sh rebuild`.
- **Login loop** — check `SERVER_BASE_URL` matches the URL in your browser
  exactly (scheme, host, port); the cookie and redirect URI both derive from it.
- **Data reset** — `down` + `up` wipes everything (PVC dies with the cluster).
