# Cloud Deployment — AKS + Entra ID

The `k8s/` directory contains the production Kubernetes manifests for running the HTTP server (dashboard + REST API + MCP Streamable HTTP) on Azure Kubernetes Service. This is the deployment behind jobcontext.ai.

For self-hosting without Azure, see the disposable local k3d cluster ([docs/local-cluster.md](local-cluster.md)) and the single-node k3s deployment under `k8s/pi/` (proven on a Raspberry Pi 4).

**Prerequisites:** Azure CLI (`az`), `kubectl`, an active Azure subscription, and existing Azure substrate — resource group, ACR, Storage Account, and an AKS cluster with OIDC issuer + workload identity.

## Deploy

Ongoing deploys are CI-driven: pushes to `main` and `qa` run [`deploy.yml`](../.github/workflows/deploy.yml) — tests + the eval smoke gate, then a Docker build pushed to ACR, then `kubectl apply` of the `k8s/` manifests (with `<ACR_NAME>`/`<IMAGE_TAG>` placeholders substituted) and a rollout wait.

To apply the manifests by hand against your own cluster:

```bash
az login && az aks get-credentials -g <rg> -n <cluster>
kubectl create namespace jcmcp
# Create the app secrets first (see "Patch the k8s secret" below), then:
sed -e "s/<ACR_NAME>/youracr/" -e "s/<IMAGE_TAG>/latest/" k8s/deployment.yaml \
  | kubectl apply -f - -n jcmcp
kubectl apply -f k8s/configmap.yaml -f k8s/pvc.yaml -f k8s/service.yaml \
  -f k8s/ingress.yaml -f k8s/cert-issuer.yaml -n jcmcp
```

The QA environment has a one-shot idempotent provisioner, [`scripts/setup-qa-env.sh`](../scripts/setup-qa-env.sh), which creates the namespace, storage account, federated credential, secrets, and configmap for `qa.jobcontext.ai` — it's the model for what a fresh-environment bootstrap needs.

On each pod start, the `seed-workspace` init container authenticates via a workload-identity federated token (no API keys in the pod), syncs workspace files from Blob Storage, and seeds `jobcontextmcp.db` from Blob on first boot only — runtime writes are preserved across restarts. A `workspace-sync` sidecar pushes PVC workspace files + the SQLite DB back to Blob every 15 minutes, so data survives pod replacement.

**LLM provider options:**

| Provider | Auth | API key required? |
|---|---|---|
| `openai` | `OPENAI_API_KEY` in k8s Secret | Yes |
| `foundry` | `DefaultAzureCredential` via workload identity | No |
| `ollama` | Self-hosted endpoint URL | No |

## Verify a live deployment

```bash
kubectl get pods -n jcmcp          # should show 2/2 Running (main + workspace-sync sidecar)
kubectl port-forward svc/jcmcp 8099:80 -n jcmcp
curl http://localhost:8099/health
```

MCP clients connect over Streamable HTTP at `/mcp` (see [client-setup.md](client-setup.md)); the dashboard requires Entra login at `/`.

## Entra ID authentication

The AKS-hosted dashboard uses Microsoft Entra ID for browser login (OAuth2 PKCE). Any Microsoft account user can be invited as a B2B guest; each guest gets their own isolated data partition on first login (blank SQLite DB + full workspace tree + placeholder resume).

**Required app registration settings:**

| Setting | Value |
|---|---|
| `signInAudience` | `AzureADMyOrg` (single-tenant) |
| Redirect URI | `https://<your-domain>/dashboard/callback` (or `http://localhost:8099/dashboard/callback` for port-forward) |
| `accessTokenAcceptedVersion` | `null` (v1 tokens) or `2` (v2 tokens) — the auth layer accepts both |
| Client secret | Rotate via **Azure Portal → App registrations → Certificates & secrets** |

**Important:** creating the app registration does NOT automatically create the service principal in your tenant. Run this once after registration, or token exchange returns `AADSTS7000229 service principal not found`:

```bash
az ad sp create --id <CLIENT_ID>
```

**Patch the k8s secret and roll out:**

```bash
kubectl create secret generic jcmcp-app-secrets \
  --from-literal=entra_client_id=<CLIENT_ID> \
  --from-literal=entra_tenant_id=<TENANT_ID> \
  --from-literal=entra_client_secret=<CLIENT_SECRET> \
  --from-literal=entra_redirect_uri=https://<your-domain>/dashboard/callback \
  --from-literal=entra_owner_oid=<YOUR_ENTRA_OID> \
  -n jcmcp --dry-run=client -o yaml | kubectl apply -f -

kubectl rollout restart deployment/jcmcp -n jcmcp
kubectl rollout status deployment/jcmcp -n jcmcp
```

**Invite a guest user:**

```bash
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/invitations" \
  --headers "Content-Type=application/json" \
  --body '{
    "invitedUserEmailAddress": "guest@example.com",
    "inviteRedirectUrl": "https://<your-domain>/dashboard/login",
    "sendInvitationMessage": true
  }'
```

The guest must accept the invitation before their first login. Their data partition is auto-provisioned on first dashboard visit — no manual setup required.

## Per-user data isolation

| User | Data path | Rule |
|---|---|---|
| Any authenticated Entra user (owner included) | `/app/data/users/{entra_oid}/` | Isolated SQLite DB + workspace; placeholder resume seeded on first login |
| Global root | `/app/data/db/` | Not a tenant destination; holds only the shared DB used for pre-auth per-user API-key lookups |

`UserDataContextMiddleware` handles routing transparently via a per-request `ContextVar` (`lib/user_context.py`) — tools and dashboard routes read and write the caller's partition with no code changes. `ENTRA_OWNER_OID` only governs contact-info fallback and owner-only UI flags; it does **not** change storage routing.

> **Never offload work with bare `run_in_executor`** — contextvars don't propagate to executor threads, which once caused a partition-escape incident in production. Background work goes through the control plane (`lib/work.py`, [control-plane.md](control-plane.md)), whose executors get partition context from the durable work-item row.

## QA environment

A parallel `qa.jobcontext.ai` environment runs on the same cluster (namespace `jcmcp-qa`, its own storage account + PVC, shared workload identity via a QA federated credential). Pushes to the `qa` branch build a `qa-<sha>` image and roll out independently of production. See `k8s/qa/` and `scripts/setup-qa-env.sh`.

## Cost controls

Changes from the 2026-10 cost review. Spend was about $330/month for an
environment with light beta traffic.

- **Blob backup writes.** The `workspace-sync` sidecar used to re-upload
  every tenant file every 15 minutes. Those writes were nearly the whole
  storage-account bill in both environments. It now uploads only files whose
  ctime changed since the last good tick. It still runs a full `upload-batch`
  on the first tick after a pod start, once a day, and whenever more than
  200 files changed. Each tick logs `upload: full batch` or
  `upload: N changed files`.
- **Monitoring is in-cluster only.** Azure Managed Grafana and Azure Monitor
  managed Prometheus (the `ama-metrics` addon and its Azure Monitor
  workspace) were removed. The dashboards live in `k8s/monitoring/`, backed
  by the in-cluster Prometheus. Don't re-enable the AKS monitoring addon
  without a reason; it re-creates both costs.
- **ACR purge.** Every deploy pushes a `<sha>` (prod) or `qa-<sha>` (QA)
  image, and Basic SKU has no retention policy. Two scheduled ACR tasks,
  one per tag family so `--keep` counts each family separately, keep the 5
  newest of each and leave `latest` and `qa-latest` alone. The currently
  deployed image is always the newest of its family, so it's never purged:

  ```bash
  az acr task create --registry jcmcpacr --name purge-prod-images \
    --cmd "acr purge --filter 'jcmcp:^[0-9a-f]{40}$' --ago 1d --keep 5 --untagged" \
    --schedule "0 4 * * *" --context /dev/null
  az acr task create --registry jcmcpacr --name purge-qa-images \
    --cmd "acr purge --filter 'jcmcp:^qa-[0-9a-f]{40}$' --ago 1d --keep 5" \
    --schedule "30 4 * * *" --context /dev/null
  ```
- **One node.** The node pool runs a single D2s v3; everything requests
  about 0.2 vCPU and 1.5 GiB. Prod and QA are already single-replica
  (`Recreate`), so a second node added no redundancy for the app itself.
  Scale back up with `az aks nodepool scale` if load grows.
