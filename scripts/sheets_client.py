"""Google Sheets client for case tracking."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from scripts.env import PROJECT_ROOT

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
TOKEN_FILE = str(PROJECT_ROOT / "token_support.json")

SHEET_HEADERS = {
    "Exchanges": ["case_id", "thread_id", "first_name", "email", "date_opened", "product", "order_number", "stage", "tracking_number", "influencer_name", "influencer_address", "notes"],
    "Returns": ["case_id", "thread_id", "first_name", "email", "date_opened", "product", "order_number", "stage", "tracking_number", "influencer_name", "influencer_address", "notes"],
    "Chargebacks": ["case_id", "thread_id", "first_name", "email", "date_opened", "product", "order_number", "stage", "notes"],
    "Failed Deliveries": ["case_id", "thread_id", "first_name", "email", "date_opened", "product", "order_number", "stage", "notes"],
}


def _get_credentials() -> Credentials:
    if not os.path.exists(TOKEN_FILE):
        raise FileNotFoundError(
            f"{TOKEN_FILE} not found. Run setup_auth.py first to authorize."
        )
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


class SheetsClient:
    def __init__(self, sheet_id: str) -> None:
        creds = _get_credentials()
        self.service = build("sheets", "v4", credentials=creds)
        self.sheet_id = sheet_id

    def find_case_by_thread_id(self, thread_id: str) -> Optional[dict]:
        """Search all tabs for a case matching thread_id. Returns case dict with _tab and _row_number."""
        for tab in SHEET_HEADERS.keys():
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range=f"'{tab}'!A:L",
            ).execute()
            rows = result.get("values", [])[1:]  # Skip header
            for i, row in enumerate(rows, start=2):
                if len(row) > 1 and row[1] == thread_id:
                    case = dict(zip(SHEET_HEADERS[tab], row))
                    case["_tab"] = tab
                    case["_row_number"] = i
                    return case
        return None

    def append_case(self, tab: str, thread_id: str, fields: dict) -> str:
        """Append a new case to tab. Returns case_id."""
        # Generate case_id based on tab
        prefix_map = {"Exchanges": "EXC", "Returns": "RET", "Chargebacks": "CHB", "Failed Deliveries": "FD"}
        prefix = prefix_map.get(tab, "CASE")

        # Get next number
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.sheet_id,
            range=f"'{tab}'!A:A",
        ).execute()
        rows = result.get("values", [])[1:]  # Skip header
        next_num = len(rows)
        case_id = f"{prefix}-{next_num:03d}"

        # Build row
        row = []
        for header in SHEET_HEADERS[tab]:
            if header == "case_id":
                row.append(case_id)
            elif header == "thread_id":
                row.append(thread_id)
            elif header == "date_opened":
                row.append(datetime.now().strftime("%Y-%m-%d"))
            else:
                row.append(fields.get(header, ""))

        # Append
        self.service.spreadsheets().values().append(
            spreadsheetId=self.sheet_id,
            range=f"'{tab}'!A:L",
            valueInputOption="USER_ENTERED",
            body={"values": [row]},
        ).execute()

        return case_id

    def update_case(self, tab: str, row_number: int, existing_case: dict, fields: dict) -> None:
        """Update an existing case row with new field values."""
        # Merge existing + new fields
        updated = dict(existing_case)
        updated.pop("_tab", None)
        updated.pop("_row_number", None)
        updated.update(fields)

        # Build row
        row = []
        for header in SHEET_HEADERS[tab]:
            row.append(updated.get(header, ""))

        # Update
        self.service.spreadsheets().values().update(
            spreadsheetId=self.sheet_id,
            range=f"'{tab}'!A{row_number}:L{row_number}",
            valueInputOption="USER_ENTERED",
            body={"values": [row]},
        ).execute()
