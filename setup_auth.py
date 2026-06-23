"""
OAuth2 setup for support@ascend.store Gmail access.
Works on headless servers (no browser required). It prints a URL you open
on your own PC, approve access, then your browser will try (and fail) to
load a localhost page — you paste that failed page's full URL back into
the terminal here.

Usage:
    python setup_auth.py [--credentials credentials.json]

You need a credentials.json from Google Cloud Console:
  1. Go to console.cloud.google.com
  2. Create a project (or use an existing one)
  3. Enable the Gmail API
  4. Create OAuth 2.0 credentials (Desktop app type)
  5. Download the JSON and save it as credentials.json here
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Resolve project root from this file's location so paths work regardless of cwd
PROJECT_ROOT = Path(__file__).resolve().parent

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/spreadsheets"]
DEFAULT_CREDS = str(PROJECT_ROOT / "credentials.json")
TOKEN_FILE = str(PROJECT_ROOT / "token_support.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize support@ascend.store Gmail access")
    parser.add_argument("--credentials", default=DEFAULT_CREDS, help="Path to credentials.json")
    args = parser.parse_args()

    if not os.path.exists(args.credentials):
        print(f"Error: {args.credentials} not found.")
        print(__doc__)
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(
        args.credentials,
        SCOPES,
        redirect_uri="http://localhost",
    )
    auth_url, _ = flow.authorization_url(prompt="consent")

    print("=" * 60)
    print("Open this URL in a browser on your own PC:")
    print()
    print(auth_url)
    print()
    print("Sign in with support@ascend.store (not your personal account).")
    print("After approving, your browser will try to load a localhost page")
    print("and FAIL TO CONNECT — that's expected, the page doesn't exist.")
    print("Copy the FULL URL from the address bar at that point (it will")
    print("start with http://localhost/?code=... and may be long).")
    print("=" * 60)

    redirect_response = input("\nPaste that full URL here and press Enter: ").strip()
    flow.fetch_token(authorization_response=redirect_response)

    creds = flow.credentials
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

    # Verify the authorized account
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    email = profile.get("emailAddress", "unknown")
    print(f"\nAuthorized as: {email}")
    print(f"Token saved to: {TOKEN_FILE}")
    if "support@" not in email:
        print("\nWarning: this doesn't look like the support account. Re-run and sign in with support@ascend.store.")


if __name__ == "__main__":
    main()
