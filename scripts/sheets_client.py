"""Google Sheets client for ASCENDI case tracking.

Mirrors gmail_client.py's exact credential-loading/refresh pattern so both
clients can safely share the same token_support.json (now authorized for
both Gmail and Sheets scopes after re-running setup_auth.py).
"""
from __future__ import annotations

import os
from datetime import date
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from scripts.env import PROJECT_ROOT

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/spreadsheets",
]
TOKEN_FILE = str(PROJECT_ROOT / "token_support.json")

CASE_ID_PREFIXES = {
    "Exchanges": "EXC",
    "Returns": "RET",
    "Chargebacks": "CHB",
    "Failed Deliveries": "FD",
}


def _get_credentials() -> Credentials:
    if not os.path.exists(TOKEN_FILE):
        raise FileNotFoundError(
            f"{TOKEN_FILE} not found. Run setup_auth.py first "
            "(with the Sheets scope added to SCOPES)."
        )
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def _quoted(tab: str) -> str:
    """Wrap a tab name for A1-notation ranges (required when it contains a space)."""
    return f"'{tab}'"


class SheetsClient:
    def __init__(self, sheet_id: str) -> None:
        creds = _get_credentials()
        self.service = build("sheets", "v4", credentials=creds)
        self.sheet_id = sheet_id
        self._header_cache: dict[str, list[str]] = {}

    # ── Header handling ──────────────────────────────────────────────────

    def _get_headers(self, tab: str) -> list[str]:
        if tab not in self._header_cache:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id, range=f"{_quoted(tab)}!1:1"
            ).execute()
            rows = result.get("values", [])
            self._header_cache[tab] = rows[0] if rows else []
        return self._header_cache[tab]

    @staticmethod
    def _row_to_dict(headers: list[str], row: list[str]) -> dict:
        padded = row + [""] * (len(headers) - len(row))
        return dict(zip(headers, padded))

    @staticmethod
    def _dict_to_row(headers: list[str], data: dict) -> list[str]:
        return [str(data.get(h, "")) for h in headers]

    # ── Lookup ───────────────────────────────────────────────────────────

    def find_case_by_thread_id(self, thread_id: str) -> Optional[dict]:
        """Search all known tabs for a row matching thread_id.

        Returns a dict of {header: value, ...} plus "_tab" and "_row_number"
        (1-indexed, header row counted) if found, else None.
        """
        for tab in CASE_ID_PREFIXES:
            headers = self._get_headers(tab)
            if "thread_id" not in headers:
                continue
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id, range=f"{_quoted(tab)}!A2:Z"
            ).execute()
            rows = result.get("values", [])
            tid_idx = headers.index("thread_id")
            for i, row in enumerate(rows):
                if len(row) > tid_idx and row[tid_idx] == thread_id:
                    case = self._row_to_dict(headers, row)
                    case["_tab"] = tab
                    case["_row_number"] = i + 2  # header row + 1-indexing
                    return case
        return None

    # ── Writes ───────────────────────────────────────────────────────────

    def _next_case_id(self, tab: str) -> str:
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.sheet_id, range=f"{_quoted(tab)}!A2:A"
        ).execute()
        count = len([r for r in result.get("values", []) if r and r[0]])
        prefix = CASE_ID_PREFIXES.get(tab, "CASE")
        return f"{prefix}-{count + 1:03d}"

    def append_case(self, tab: str, thread_id: str, fields: dict) -> str:
        """Append a new case row. `fields` may contain any of
        first_name/email/order_number/product/stage/tracking_number/notes/
        influencer_name/influencer_address. Returns the generated case_id."""
        headers = self._get_headers(tab)
        today = date.today().isoformat()
        data = {
            "case_id": self._next_case_id(tab),
            "thread_id": thread_id,
            "date_opened": today,
            "last_updated": today,
            **fields,
        }
        row = self._dict_to_row(headers, data)
        self.service.spreadsheets().values().append(
            spreadsheetId=self.sheet_id,
            range=f"{_quoted(tab)}!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        return data["case_id"]

    def update_case(self, tab: str, row_number: int, existing: dict, updates: dict) -> None:
        """Overwrite a case row: merge `updates` onto `existing` (as returned by
        find_case_by_thread_id) and bump last_updated."""
        headers = self._get_headers(tab)
        merged = {**existing, "last_updated": date.today().isoformat(), **updates}
        row = self._dict_to_row(headers, merged)
        last_col = chr(ord("A") + len(headers) - 1)
        self.service.spreadsheets().values().update(
            spreadsheetId=self.sheet_id,
            range=f"{_quoted(tab)}!A{row_number}:{last_col}{row_number}",
            valueInputOption="USER_ENTERED",
            body={"values": [row]},
        ).execute()
