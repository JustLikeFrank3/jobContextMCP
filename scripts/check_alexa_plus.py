"""Read-only native Alexa+ discovery preflight; never logs or uses credentials.

This probes public metadata only. It does not certify account linking, tool
latency, user isolation or device availability.
"""
import json
import sys
from urllib.parse import urlsplit

import httpx


def inspect_endpoint(endpoint):
    parts = urlsplit(endpoint)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Provide an HTTPS MCP endpoint without credentials, query or fragment.")
    origin = f"{parts.scheme}://{parts.netloc}"
    with httpx.Client(timeout=15, follow_redirects=False) as client:
        probe = client.post(endpoint, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "alexa-plus-preflight", "version": "1"}}},
            headers={"Accept": "application/json, text/event-stream"})
        prm = client.get(origin + "/.well-known/oauth-protected-resource")
        auth = client.get(origin + "/.well-known/oauth-authorization-server")
    resource = prm.json() if prm.status_code == 200 else {}
    server = auth.json() if auth.status_code == 200 else {}
    return {"endpoint": endpoint, "public_checks_only": True,
        "unauthenticated_status": probe.status_code,
        "unauthenticated_is_401": probe.status_code == 401,
        "www_authenticate_present": "www-authenticate" in probe.headers,
        "resource_metadata_available": prm.status_code == 200,
        "advertised_resource": resource.get("resource"),
        "resource_exactly_matches_endpoint": resource.get("resource") == endpoint,
        "authorization_metadata_available": auth.status_code == 200,
        "pkce_s256_advertised": "S256" in server.get("code_challenge_methods_supported", []),
        "client_credentials_advertised": "client_credentials" in server.get("grant_types_supported", []),
        "openid_scope_advertised": "openid" in resource.get("scopes_supported", []),
        "dcr_advertised": bool(server.get("registration_endpoint")),
        "not_verified": ["Amazon onboarding access", "service versus user scope enforcement",
                         "account linking and refresh", "authenticated tool latency under 500ms",
                         "MCP Apps visuals", "physical Alexa+ device"]}


if __name__ == "__main__":
    print(json.dumps(inspect_endpoint(sys.argv[1] if len(sys.argv) > 1 else "https://qa.jobcontext.ai/mcp"), indent=2))
