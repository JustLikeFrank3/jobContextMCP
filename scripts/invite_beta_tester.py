#!/usr/bin/env python3
"""
invite_beta_tester.py — Send an Azure B2B guest invite and email setup PDFs.

Usage:
    python3 scripts/invite_beta_tester.py \
        --email kate@example.com \
        --name "Kate Griebel"

Requirements:
    pip install azure-identity azure-mgmt-authorization msrestazure

Environment (set in shell or .env.deploy):
    ENTRA_TENANT_ID        — Azure AD tenant (default: jobcontext.ai tenant)
    MAILER_CLIENT_ID       — jobcontext-mailer app registration client ID
    MAILER_CLIENT_SECRET   — jobcontext-mailer client secret value

The script will:
    1. Send an Entra B2B guest invitation to the provided email
    2. Email the recipient the two setup PDFs as attachments
       - Claude Desktop Setup Guide.pdf
       - VSCode Setup Guide.pdf
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

TENANT_ID    = os.environ.get("MAILER_TENANT_ID", "52e316a2-ae6c-4049-9c9d-9ead2dcdbe78")
REDIRECT_URL = "https://jobcontext.ai"
FROM_EMAIL   = "admin@jobcontext.ai"
FROM_NAME    = "Frank MacBride"

BETA_TESTERS_PATH = Path(__file__).parent.parent / "data" / "beta_testers.json"

PDFS_DIR = Path(
    "/Volumes/MiniDougJr-Appendix/fvm3-appendix/Library/Mobile Documents/"
    "com~apple~CloudDocs/Projects/jobContextMCP-SelfSetup/personal"
)
SETUP_PDFS = [
    "Claude Desktop Setup Guide.pdf",   # note: intentional typo in filename
    "VSCode Setup Guide.pdf",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def send_b2b_invite(email: str, display_name: str) -> str:
    """Send Azure B2B guest invitation via az CLI. Returns the invitation URL."""
    print(f"  Sending B2B invite to {email}...")
    result = subprocess.run(
        [
            "az", "rest",
            "--method", "POST",
            "--uri", "https://graph.microsoft.com/v1.0/invitations",
            "--body", json.dumps({
                "invitedUserEmailAddress": email,
                "invitedUserDisplayName": display_name,
                "inviteRedirectUrl": REDIRECT_URL,
                "sendInvitationMessage": True,
            }),
            "--query", "inviteRedeemUrl",
            "--output", "tsv",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ERROR: Graph API invitation failed (exit {result.returncode})")
        print(f"  STDOUT: {result.stdout.strip()}")
        print(f"  STDERR: {result.stderr.strip()}")
        sys.exit(1)
    url = result.stdout.strip()
    print(f"  Invite sent. Redemption URL: {url}")
    return url


def _get_graph_token(client_id: str, client_secret: str) -> str:
    """Obtain a client-credentials token for Microsoft Graph."""
    token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     client_id,
        "client_secret": client_secret,
        "scope":         "https://graph.microsoft.com/.default",
    }).encode()
    req = urllib.request.Request(token_url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())["access_token"]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"  ERROR: token request failed HTTP {exc.code}: {body}")
        sys.exit(1)


def send_setup_email(email: str, display_name: str, invite_url: str, _unused: str = "") -> None:
    """Send a welcome email with setup PDFs via Microsoft Graph client credentials."""
    client_id     = os.environ.get("MAILER_CLIENT_ID", "")
    client_secret = os.environ.get("MAILER_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("ERROR: Set MAILER_CLIENT_ID and MAILER_CLIENT_SECRET in your environment.")
        sys.exit(1)

    first_name = display_name.split()[0]
    body_text = f"""Hey {first_name},

You're in. Here's everything you need to get set up.

Step 1: Accept your Microsoft invite
{invite_url}

You'll be asked to sign in with a Microsoft account. If you don't have one tied to {email}, Microsoft will walk you through creating one (it's free and doesn't require switching email providers).

Step 2: Follow the setup guide for your preferred client
I've attached two guides:
- Claude Desktop Setup Guide (recommended starting point)
- VS Code + Copilot Setup Guide

Both connect to the same live server at jobcontext.ai. Pick whichever AI client you use most.

Step 3: Let me know how it goes
Reply here or ping me on LinkedIn. If anything breaks, that's a bug report and I want it.

Thanks for being an early tester.

Frank
"""

    attachments = []
    for pdf_name in SETUP_PDFS:
        pdf_path = PDFS_DIR / pdf_name
        if not pdf_path.exists():
            print(f"  WARNING: PDF not found, skipping: {pdf_path}")
            continue
        with open(pdf_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        attachments.append({
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": pdf_name,
            "contentType": "application/pdf",
            "contentBytes": encoded,
        })
        print(f"  Attached: {pdf_name}")

    payload = json.dumps({
        "message": {
            "subject": "You're in \u2014 jobContext beta setup",
            "body": {"contentType": "Text", "content": body_text},
            "toRecipients": [{"emailAddress": {"address": email, "name": display_name}}],
            "attachments": attachments,
        },
        "saveToSentItems": True,
    }).encode("utf-8")

    print(f"  Sending setup email to {email} via Microsoft Graph...")
    token = _get_graph_token(client_id, client_secret)
    req = urllib.request.Request(
        f"https://graph.microsoft.com/v1.0/users/{FROM_EMAIL}/sendMail",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"  ERROR: Graph sendMail returned HTTP {exc.code}")
        print(f"  {body}")
        sys.exit(1)
    print("  Email sent.")


def register_beta_tester(name: str, email: str, source: str) -> None:
    """Append a new entry to beta_testers.json."""
    with open(BETA_TESTERS_PATH) as f:
        data = json.load(f)

    # Idempotent: skip if already registered by email
    existing = [t for t in data["testers"] if t.get("contact", "").lower() == email.lower()]
    if existing:
        print(f"  Already in beta_testers.json (id {existing[0]['id']}), skipping.")
        return

    next_id = max(t["id"] for t in data["testers"]) + 1
    today = date.today().isoformat()
    entry = {
        "id": next_id,
        "name": name,
        "contact": email,
        "source": source,
        "entra_oid": "",
        "signed_up": today,
        "status": "invited",
        "os": "",
        "ai_client": "",
        "setup_completed": False,
        "hbdi_completed": False,
        "bugs": [],
        "feedback": [],
        "notes": f"B2B invite sent {date.today().strftime('%B %-d %Y')}.",
        "last_updated": today,
    }
    data["testers"].append(entry)

    with open(BETA_TESTERS_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Registered in beta_testers.json as id {next_id}.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Invite a jobContext beta tester.")
    parser.add_argument("--email", required=True, help="Tester's email address")
    parser.add_argument("--name",  required=True, help="Tester's display name (quoted)")
    parser.add_argument(
        "--source",
        default="direct",
        help="How this tester was sourced (default: direct). e.g. linkedin, referral, direct",
    )
    parser.add_argument(
        "--skip-invite",
        action="store_true",
        help="Skip the B2B invite step (use if already invited)",
    )
    parser.add_argument(
        "--invite-url",
        default=REDIRECT_URL,
        help="Override the invite URL in the email body (use with --skip-invite)",
    )
    args = parser.parse_args()

    print(f"\nInviting beta tester: {args.name} <{args.email}>")
    print("─" * 50)

    invite_url = args.invite_url
    if not args.skip_invite:
        invite_url = send_b2b_invite(args.email, args.name)

    send_setup_email(args.email, args.name, invite_url)
    register_beta_tester(args.name, args.email, args.source)

    print("─" * 50)
    print("Done.")


if __name__ == "__main__":
    main()
