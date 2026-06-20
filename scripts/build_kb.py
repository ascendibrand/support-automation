"""
Build the RAG knowledge base from past support threads.

Scans all threads where support@ascend.store has sent a reply, extracts
Q&A pairs (inbound question + all outbound replies concatenated), and
saves them to kb.json.

Usage:
    python scripts/build_kb.py [--output kb.json] [--max-threads 500]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timezone

# Allow running from project root or scripts/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.gmail_client import GmailClient, Thread


def thread_to_kb_entry(thread: Thread) -> dict | None:
    """Convert a thread to a KB entry. Returns None if no outbound replies."""
    outbound = thread.outbound_messages
    inbound = thread.inbound_messages
    if not outbound or not inbound:
        return None

    # Concatenate all inbound messages as the "question"
    question_parts = []
    for msg in inbound:
        question_parts.append(msg.body.strip())
    question = "\n\n---\n\n".join(p for p in question_parts if p)

    # Concatenate all outbound replies as the "answer"
    answer_parts = []
    for msg in outbound:
        answer_parts.append(msg.body.strip())
    answer = "\n\n---\n\n".join(p for p in answer_parts if p)

    if not question or not answer:
        return None

    # Use the timestamp of the most recent outbound reply for recency scoring
    latest_reply_ts = max(m.timestamp for m in outbound)

    return {
        "thread_id": thread.id,
        "subject": thread.subject,
        "question": question,
        "answer": answer,
        "replied_at": latest_reply_ts.astimezone(timezone.utc).isoformat(),
    }


def build_kb(output_path: str = "kb.json", max_threads: int = 500) -> None:
    print("Connecting to Gmail...")
    client = GmailClient()
    print(f"Authorized as: {client.support_email}")

    print(f"Fetching up to {max_threads} replied threads...")
    threads = client.fetch_all_replied_threads(max_results=max_threads)
    print(f"Found {len(threads)} threads with outbound replies.")

    entries = []
    for thread in threads:
        entry = thread_to_kb_entry(thread)
        if entry:
            entries.append(entry)

    entries.sort(key=lambda e: e["replied_at"], reverse=True)

    with open(output_path, "w") as f:
        json.dump(entries, f, indent=2)

    print(f"Knowledge base saved: {output_path} ({len(entries)} entries)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build RAG knowledge base from Gmail threads")
    parser.add_argument("--output", default="kb.json", help="Output JSON file (default: kb.json)")
    parser.add_argument("--max-threads", type=int, default=500, help="Max threads to scan")
    args = parser.parse_args()
    build_kb(output_path=args.output, max_threads=args.max_threads)


if __name__ == "__main__":
    main()
