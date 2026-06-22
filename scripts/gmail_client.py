"""Gmail API wrapper — fetches threads and manages labels/drafts."""
from __future__ import annotations

import base64
import email as email_lib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from scripts.env import PROJECT_ROOT

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
TOKEN_FILE = str(PROJECT_ROOT / "token_support.json")


@dataclass
class Message:
    id: str
    thread_id: str
    sender: str
    recipient: str
    subject: str
    body: str
    timestamp: datetime
    is_outbound: bool  # sent by the support account


@dataclass
class Thread:
    id: str
    subject: str
    messages: list[Message] = field(default_factory=list)

    @property
    def last_message(self) -> Optional[Message]:
        return self.messages[-1] if self.messages else None

    @property
    def last_is_outbound(self) -> bool:
        return bool(self.last_message and self.last_message.is_outbound)

    @property
    def inbound_messages(self) -> list[Message]:
        return [m for m in self.messages if not m.is_outbound]

    @property
    def outbound_messages(self) -> list[Message]:
        return [m for m in self.messages if m.is_outbound]


def _get_credentials() -> Credentials:
    if not os.path.exists(TOKEN_FILE):
        raise FileNotFoundError(
            f"{TOKEN_FILE} not found. Run setup_auth.py first to authorize support@ascend.store."
        )
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def _decode_body(payload: dict) -> str:
    """Extract plain-text body from a Gmail message payload."""
    def _extract(part: dict) -> str:
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        if mime.startswith("multipart/"):
            for sub in part.get("parts", []):
                result = _extract(sub)
                if result:
                    return result
        return ""

    return _extract(payload).strip()


def _parse_address(raw: str) -> str:
    """Extract email address from a header like 'Name <addr@domain.com>'."""
    match = re.search(r"<([^>]+)>", raw)
    return match.group(1).lower() if match else raw.strip().lower()


def _parse_message(raw: dict, support_email: str) -> Message:
    headers = {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}
    sender = _parse_address(headers.get("from", ""))
    recipient = _parse_address(headers.get("to", ""))
    subject = headers.get("subject", "(no subject)")
    ts_ms = int(raw.get("internalDate", 0))
    timestamp = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    body = _decode_body(raw.get("payload", {}))
    is_outbound = sender == support_email.lower()
    return Message(
        id=raw["id"],
        thread_id=raw["threadId"],
        sender=sender,
        recipient=recipient,
        subject=subject,
        body=body,
        timestamp=timestamp,
        is_outbound=is_outbound,
    )


class GmailClient:
    def __init__(self) -> None:
        creds = _get_credentials()
        self.service = build("gmail", "v1", credentials=creds)
        profile = self.service.users().getProfile(userId="me").execute()
        self.support_email: str = profile["emailAddress"]
        self._label_cache: dict[str, str] = {}

    # ── Label management ────────────────────────────────────────────────────

    def _get_or_create_label(self, name: str) -> str:
        if name in self._label_cache:
            return self._label_cache[name]
        labels = self.service.users().labels().list(userId="me").execute().get("labels", [])
        for lbl in labels:
            if lbl["name"] == name:
                self._label_cache[name] = lbl["id"]
                return lbl["id"]
        created = self.service.users().labels().create(
            userId="me",
            body={
                "name": name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        ).execute()
        self._label_cache[name] = created["id"]
        return created["id"]

    def apply_label(self, thread_id: str, label_name: str) -> None:
        label_id = self._get_or_create_label(label_name)
        self.service.users().threads().modify(
            userId="me",
            id=thread_id,
            body={"addLabelIds": [label_id]},
        ).execute()

    # ── Thread fetching ──────────────────────────────────────────────────────

    def get_thread(self, thread_id: str) -> Thread:
        raw = self.service.users().threads().get(
            userId="me", id=thread_id, format="full"
        ).execute()
        messages = [_parse_message(m, self.support_email) for m in raw.get("messages", [])]
        messages.sort(key=lambda m: m.timestamp)
        subject = messages[0].subject if messages else "(no subject)"
        return Thread(id=thread_id, subject=subject, messages=messages)

    def list_unhandled_threads(
        self,
        no_action_label: str = "Support/No Action",
        action_label: str = "Support/Action Required",
        max_results: int = 50,
    ) -> list[Thread]:
        """Return inbox threads that haven't been labeled by us yet."""
        # Build exclusion query using label names
        query = f'in:inbox -label:"{no_action_label}" -label:"{action_label}"'
        response = self.service.users().threads().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        thread_stubs = response.get("threads", [])
        threads = []
        for stub in thread_stubs:
            try:
                threads.append(self.get_thread(stub["id"]))
            except Exception as exc:
                print(f"  Warning: could not fetch thread {stub['id']}: {exc}")
        return threads

    def fetch_all_replied_threads(self, max_results: int = 500) -> list[Thread]:
        """Fetch threads where we have at least one outbound reply (for KB building)."""
        # Fetch sent messages to find thread IDs we've replied in
        response = self.service.users().messages().list(
            userId="me", labelIds=["SENT"], maxResults=max_results
        ).execute()
        msgs = response.get("messages", [])
        seen_thread_ids: set[str] = set()
        threads = []
        for msg_stub in msgs:
            tid = msg_stub.get("threadId")
            if tid and tid not in seen_thread_ids:
                seen_thread_ids.add(tid)
                try:
                    thread = self.get_thread(tid)
                    if thread.outbound_messages:
                        threads.append(thread)
                except Exception as exc:
                    print(f"  Warning: could not fetch thread {tid}: {exc}")
        return threads

    # ── Draft creation ───────────────────────────────────────────────────────

    def create_draft(self, thread_id: str, to: str, subject: str, body: str) -> str:
        """Create a Gmail draft as a reply in the given thread. Returns draft ID."""
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        mime = MIMEText(body, "plain")
        mime["to"] = to
        mime["from"] = self.support_email
        mime["subject"] = subject
        raw_bytes = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        draft = self.service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw_bytes, "threadId": thread_id}},
        ).execute()
        return draft["id"]
