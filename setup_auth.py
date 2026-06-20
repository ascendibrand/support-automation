"""
OAuth2 setup for support@ascend.store Gmail access.

Run this once interactively to authorize the account. It opens a browser
window for Google sign-in and stores the token in token_support.json.

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

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
DEFAULT_CREDS = "credentials.json"
TOKEN_FILE = "token_support.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize support@ascend.store Gmail access")
    parser.add_argument("--credentials", default=DEFAULT_CREDS, help="Path to credentials.json")
    args = parser.parse_args()

    if not os.path.exists(args.credentials):
        print(f"Error: {args.credentials} not found.")
        print(__doc__)
        sys.exit(1)

    print("Opening browser for Google sign-in...")
    print("Sign in with support@ascend.store (not your personal account).\n")

    flow = InstalledAppFlow.from_client_secrets_file(args.credentials, SCOPES)
    creds = flow.run_local_server(port=0)

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
