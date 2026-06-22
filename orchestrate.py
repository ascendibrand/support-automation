"""
Support email automation — main orchestration script.

Flow for each unhandled inbox thread:
  1. Hard rule: if last message is from support → "No Action" (no API call)
  2. Claude Haiku classifies: "No Action" or "Action Required"
  3. Apply Gmail label
  4. If "Action Required": RAG retrieval → Claude Opus drafts reply → Gmail draft created

Usage:
    python orchestrate.py [--max-threads 50] [--kb kb.json] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path

from scripts.env import PROJECT_ROOT, load_dotenv

load_dotenv()

import anthropic

from scripts.gmail_client import GmailClient, Thread
from scripts.rag import RAGRetriever, format_context

LABEL_NO_ACTION = "Support/No Action"
LABEL_ACTION_REQUIRED = "Support/Action Required"

MODEL_CLASSIFY = "claude-haiku-4-5-20251001"
MODEL_DRAFT = "claude-haiku-4-5-20251001"


def load_directive(name: str) -> str:
    path = Path(__file__).parent / "directives" / f"{name}.txt"
    return path.read_text().strip()


def format_thread_for_prompt(thread: Thread) -> str:
    parts = [f"Subject: {thread.subject}\n"]
    for msg in thread.messages:
        direction = "FROM SUPPORT" if msg.is_outbound else "FROM CUSTOMER"
        ts = msg.timestamp.strftime("%Y-%m-%d %H:%M UTC")
        parts.append(f"[{direction} — {ts}]\n{msg.body.strip()}")
    return "\n\n".join(parts)


def classify_thread(client: anthropic.Anthropic, thread: Thread) -> tuple[str, str]:
    """Return (classification, reason). Classification is 'Action Required' or 'No Action'."""
    directive = load_directive("classify")
    thread_text = format_thread_for_prompt(thread)

    response = client.messages.create(
        model=MODEL_CLASSIFY,
        max_tokens=256,
        system=directive,
        messages=[{"role": "user", "content": thread_text}],
    )
    raw = response.content[0].text.strip()

    # Strip markdown code fences if the model wraps JSON
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
        classification = parsed.get("classification", "No Action")
        reason = parsed.get("reason", "")
    except json.JSONDecodeError:
        # Fallback: look for keywords in raw output
        if "action required" in raw.lower():
            classification, reason = "Action Required", "Classifier returned non-JSON output"
        else:
            classification, reason = "No Action", "Classifier returned non-JSON output"

    return classification, reason


def draft_reply(
    client: anthropic.Anthropic,
    thread: Thread,
    rag: RAGRetriever | None,
) -> str:
    """Return the drafted reply body."""
    directive = load_directive("draft")
    thread_text = format_thread_for_prompt(thread)

    # RAG context
    rag_context = ""
    if rag is not None:
        last_inbound = thread.inbound_messages[-1] if thread.inbound_messages else None
        query = (last_inbound.body if last_inbound else "") + " " + thread.subject
        results = rag.retrieve(query, top_k=5)
        rag_context = format_context(results)

    user_content = f"{thread_text}\n\n---\nRelevant past replies for reference:\n{rag_context}"

    response = client.messages.create(
        model=MODEL_DRAFT,
        max_tokens=1024,
        system=directive,
        messages=[{"role": "user", "content": user_content}],
    )
    return response.content[0].text.strip()


def run(
    max_threads: int = 50,
    kb_path: str = str(PROJECT_ROOT / "kb.json"),
    dry_run: bool = False,
) -> None:
    print("=== Support Email Automation ===\n")

    ai = anthropic.Anthropic()  # ANTHROPIC_API_KEY loaded from .env or environment

    print("Connecting to Gmail...")
    gmail = GmailClient()
    print(f"Authorized as: {gmail.support_email}\n")

    # Load RAG if KB exists
    rag: RAGRetriever | None = None
    if os.path.exists(kb_path):
        print(f"Loading knowledge base from {kb_path}...")
        rag = RAGRetriever(kb_path=kb_path)
        print(f"Loaded {len(rag.entries)} KB entries.\n")
    else:
        print(f"No knowledge base found at {kb_path}. Drafts will be written without RAG context.")
        print("Run 'python scripts/build_kb.py' to build it.\n")

    print(f"Fetching up to {max_threads} unhandled inbox threads...\n")
    threads = gmail.list_unhandled_threads(
        no_action_label=LABEL_NO_ACTION,
        action_label=LABEL_ACTION_REQUIRED,
        max_results=max_threads,
    )

    if not threads:
        print("Inbox is clear — no unhandled threads found.")
        return

    print(f"Found {len(threads)} unhandled threads.\n")
    print("-" * 60)

    stats = {"no_action": 0, "action_required": 0, "drafts_created": 0, "errors": 0}

    for i, thread in enumerate(threads, 1):
        print(f"[{i}/{len(threads)}] {thread.subject[:70]}")

        try:
            # Hard rule: last message from support → No Action, skip LLM
            if thread.last_is_outbound:
                reason = "last message is from support"
                print(f"  → No Action (hard rule: {reason})")
                if not dry_run:
                    gmail.apply_label(thread.id, LABEL_NO_ACTION)
                stats["no_action"] += 1
                continue

            # Classify with Haiku
            classification, reason = classify_thread(ai, thread)
            print(f"  → {classification} ({reason})")

            if not dry_run:
                label = LABEL_ACTION_REQUIRED if classification == "Action Required" else LABEL_NO_ACTION
                gmail.apply_label(thread.id, label)

            if classification == "No Action":
                stats["no_action"] += 1
                continue

            stats["action_required"] += 1

            # Draft reply with Opus
            print("  Drafting reply...")
            reply_body = draft_reply(ai, thread, rag)

            if dry_run:
                preview = textwrap.indent(reply_body[:300], "    ")
                print(f"  [DRY RUN] Draft preview:\n{preview}")
                if len(reply_body) > 300:
                    print("    [...]")
            else:
                # Find who to reply to (last inbound sender)
                last_inbound = thread.inbound_messages[-1] if thread.inbound_messages else None
                to_addr = last_inbound.sender if last_inbound else ""
                draft_id = gmail.create_draft(
                    thread_id=thread.id,
                    to=to_addr,
                    subject=thread.subject,
                    body=reply_body,
                )
                print(f"  Draft created: {draft_id}")
                stats["drafts_created"] += 1

        except Exception as exc:
            print(f"  ERROR: {exc}")
            stats["errors"] += 1

    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  No Action:       {stats['no_action']}")
    print(f"  Action Required: {stats['action_required']}")
    print(f"  Drafts created:  {stats['drafts_created']}")
    if stats["errors"]:
        print(f"  Errors:          {stats['errors']}")
    if dry_run:
        print("\n  (dry-run mode — no Gmail changes were made)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Support email automation")
    parser.add_argument("--max-threads", type=int, default=50, help="Max inbox threads to process")
    parser.add_argument("--kb", default=str(PROJECT_ROOT / "kb.json"), help="Path to knowledge base JSON")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and draft but don't write to Gmail",
    )
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable is not set.")
        sys.exit(1)

    run(max_threads=args.max_threads, kb_path=args.kb, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
