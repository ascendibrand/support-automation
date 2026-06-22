# ASCENDI Support Automation — Project Handoff

This document is a complete handoff so a new Claude (or a new Claude Code session) can pick up
this project with full context. Paste it into a new chat to get instantly caught up. A copy
should also live in the GitHub repo so any Claude Code session can read it.

Owner: Leo (ASCENDI brand — e-commerce apparel). Communicates casually, prefers exact
copy-pasteable commands and step-by-step guidance over abstract explanation.

---

## 1. WHAT THIS PROJECT IS

An autonomous customer-support email system for an e-commerce apparel brand. Two systems were
explored; the LIVE one is the **Python server system**. (A parallel Make.com scenario also
exists but the server system is the chosen production path.)

**What the live system currently does (Phase 1 — DONE and running 24/7):**
- Watches the support Gmail inbox.
- Classifies each unhandled email as "Action Required" or "No Action" and applies a matching
  Gmail label.
- For Action Required (real human customer needing a reply), it DRAFTS a reply — never sends.
  Human reviews and sends manually.
- Drafting uses RAG over the inbox's own past replies (132 Q&A pairs extracted), weighted to
  recent answers.
- Runs automatically every 2 minutes via cron on an always-on server.

**What is NOT built yet (Phase 2 — the next big build):**
- Google Sheets case tracking with separate tabs for Exchanges / Returns / Chargebacks.
- AI identifying whether a customer email is an exchange/return/chargeback and filing it to the
  correct tab with extracted info (name, email, order #, product).
- Stage tracking via dropdowns that update as the email thread progresses, e.g.:
  reached out → confirmed proceed → sent influencer address → tracking number received →
  delivered to influencer → invoice (€15) sent → exchange shipped → done. Returns are similar
  but no invoice/replacement (refund instead). Chargebacks get their own flow.
- Telegram bot for URGENT actions only (e.g. failed deliveries needing after-sales team, send
  invoice, send influencer address). Routine stuff does NOT ping Telegram; only genuinely
  urgent/action-needed items do.
- Failed-delivery handling: customers reporting failed deliveries need immediate Telegram alert
  to reach out to after-sales team / postal carriers.

---

## 2. INFRASTRUCTURE & ACCOUNTS (critical — read carefully)

These live on DIFFERENT accounts on purpose:

- **Server:** Hetzner Cloud VPS. Name `support-server`, type CX23 (x86, 2 vCPU, 4GB, 40GB),
  location Nuremberg (eu-central). Public IPv4: `46.224.144.130`. OS: Ubuntu 26.04.
  Billed ~€6.59/month, flat (does NOT scale with how often it runs). Accessed via the Hetzner
  browser console (no SSH key was set; root password login).
- **GitHub repo:** `github.com/ascendibrand/support-automation`. The code lives here. Account:
  ascendibrand.
- **Anthropic API (the bot's brain):** on a SEPARATE email account ("Ascendi" org in the
  Anthropic console). Has credit (~$19 balance, payment method linked). THIS is what keeps the
  bot running. It is independent of any Claude.ai chat subscription. Keep this email/billing
  alive — if it lapses, the bot stops.
- **Claude.ai / Claude Code subscription:** moving to ascendibrand@gmail.com. Only needed for
  BUILDING new features, not for running the live system. Losing/switching it does not affect
  the running bot.
- **The support inbox the bot operates on:** `ascendibrand@gmail.com`. (support@ascendi.store
  forwards into it, so the bot was pointed at ascendibrand@gmail.com directly. This means the
  bot sees the whole inbox, and relies on the classifier to mark non-support mail "No Action.")

Models in use: classification = `claude-haiku-4-5`; drafting = `claude-opus` (confirm exact
current model string in the Anthropic console before changing anything — strings update).

---

## 3. CODE STRUCTURE (on server at /root/support-automation and in the GitHub repo)

```
support-automation/
├── setup_auth.py        # One-time Gmail OAuth (headless/manual code flow)
├── orchestrate.py       # Main script: classify + draft loop (run by cron)
├── credentials.json     # Google OAuth client (Desktop app) — NOT in git (deleted from repo)
├── token_support.json   # Saved Gmail auth token (on server only)
├── .env                 # ANTHROPIC_API_KEY=... (on server only, NOT in git)
├── kb.json              # RAG knowledge base (132 Q&A pairs from past replies)
├── requirements.txt
├── DEPLOYMENT.md        # Deploy steps (written by Claude Code)
├── directives/
│   ├── classify.txt     # Classification system prompt (Layer 1)
│   └── draft.txt        # Drafting system prompt (Layer 1)
└── scripts/
    ├── gmail_client.py  # Gmail API: threads.get, labels, create draft
    ├── build_kb.py      # Builds kb.json from inbox history
    ├── rag.py           # TF-IDF + recency-decay retrieval
    └── env.py           # Minimal .env loader (absolute paths, doesn't override real exports)
```

3-layer architecture: directives (editable prompts) + execution scripts (deterministic) +
Claude orchestration (the LLM calls).

Key technical decisions baked in:
- Uses `threads.get()` not `messages.get()` (needs sent messages to know if already replied).
- HARD RULE before any LLM call: if last message in thread is from support → auto "No Action",
  no API call. (Saves cost, avoids false positives on handled threads.)
- RAG concatenates ALL outbound replies per thread, not just first/last.
- Recency decay: `score = tfidf_similarity * exp(-0.005 * days_old)`. Pure stdlib TF-IDF.
- `from __future__ import annotations` at top of scripts (Python 3.9+ type-hint safety).
- All file paths absolute, anchored via `Path(__file__).resolve()`, so cron works from any cwd.
- `.env` loaded at top of orchestrate.py/build_kb.py before the anthropic import.

---

## 4. HOW IT RUNS (live, 24/7)

Cron job installed (every 2 minutes):
```
*/2 * * * * cd /root/support-automation && venv/bin/python orchestrate.py >> logs/run.log 2>&1
```
Logs to `/root/support-automation/logs/run.log`.

To operate the server:
- Hetzner console → server `support-server` → Console button → login `root` + password.
- Activate venv for manual commands: `cd support-automation` then `source venv/bin/activate`
- Run manually (live): `venv/bin/python orchestrate.py`
- Dry run (no drafts created): `python orchestrate.py --dry-run`
- Rebuild knowledge base: `python scripts/build_kb.py`
- View cron: `crontab -l`   Edit cron: `crontab -e`
- Check logs: `cat logs/run.log`

---

## 5. HARD-WON GOTCHAS (these cost hours — don't repeat them)

1. **The Hetzner browser console mangles pasted text badly.** It (a) truncated long pastes,
   (b) flipped Caps Lock state (caps off = capitals), (c) turned `&&` into `77`, `>` into `.`,
   `$` into `4`, and underscores `_` into dashes `-`, and (d) INSERTED LINE BREAKS into long
   pasted strings. The API key 401 saga was ultimately caused by a newline pasted into the
   MIDDLE of the key, splitting it across two lines so only a 40-char fragment was read.
   - Fix that finally worked: verify length with `grep ANTHROPIC_API_KEY .env | wc -c`
     (should be ~127 for a full key on its own line). If short, a line break split the key —
     open nano and join the halves into ONE line.
   - For transferring files reliably, the Git method worked (commit file to repo, `git pull`
     on server). GitHub secret-scanning blocks committing API keys; you can "Allow Secret"
     then delete + rotate after, OR avoid putting keys in git entirely.
   - If the caps/keyboard goes weird, CLOSE and REOPEN the console (resets keyboard state).
     Ctrl+Alt+Del / reopening the console does NOT delete files — everything is on disk.

2. **Google OAuth must be a "Desktop app" client** (not "Web application") for the headless
   server flow. Desktop clients have a client_secret; if you see no secret, you picked the
   wrong type.

3. **Headless auth:** `flow.run_local_server()` fails on the server (no browser). The script
   was changed to the manual flow: prints a URL → open on your PC → sign in as
   ascendibrand@gmail.com → "Google hasn't verified this app" → Advanced → Go to (unsafe) →
   approve → paste the code back. (Uses oob redirect; it worked but oob is deprecated — if it
   ever breaks, switch to a newer manual flow.)

4. **API 401 "invalid x-api-key" is misleading** — it can mean wrong key, split key, no
   credit, or wrong org. Check: key length (127), account credit, and that the key belongs to
   the funded org.

5. **Rate limit (429)** appears only on big one-time batches (50 emails at once hit the
   50k-input-tokens/minute tier limit). Normal 2-minute runs process few emails and won't hit
   it. Tier raises automatically with spend; or add a small delay between calls if needed.

6. **Env var must persist for cron.** `export` only lasts the session. The key lives in `.env`
   and `scripts/env.py` loads it. Cron has no exported vars, so `.env` is essential.

---

## 6. COST MODEL
- Hetzner server: flat ~€6.59/month regardless of run frequency or volume.
- Anthropic API: per email classified, but the hard rule skips already-replied threads for
  free, and Haiku classification is cheap. Drafting (Opus) only fires on action-required mail.
  Realistically a few dollars/month at moderate volume. Storage is a non-issue (40GB; kb.json
  is tiny; sheet data lives in Google, not the server).

---

## 7. NEXT PHASE — what to build next (Phase 2 spec seed)

Build the case-tracking + Telegram layer ON TOP of the existing classify+draft system, same
3-layer architecture, same server. Requirements (from the owner):

- After classifying a customer email, also determine if it's exchange / return / chargeback /
  general. Only exchange/return/chargeback get filed to a Google Sheet (general gets a draft
  only; non-customer gets nothing).
- One master Google Sheet, tabs: Exchanges, Returns, Chargebacks. File the case to the matching
  tab with extracted info (first name, email, order #, product, date, stage).
- Stage tracking via dropdown column, updated as the thread progresses. Exchange stages (draft,
  refine exact wording with owner): reached out → confirmed proceed → sent influencer address →
  tracking number received → delivered to influencer → €15 invoice sent → invoice paid →
  exchange shipped → content/done. Returns: same minus invoice/replacement (refund instead).
  Chargebacks: own flow (TBD).
- When the owner replies and the customer replies back, the system updates the sheet stage based
  on the new message (it re-reads the thread and advances the stage).
- Telegram bot: notify ONLY for urgent/action-needed items — e.g. failed delivery (reach out to
  after-sales/postal carrier), send invoice, send influencer address, chargebacks. Routine
  steps do NOT ping. The AI must identify what's urgent.
- Failed-delivery emails are a priority case: immediate Telegram alert to action with after-sales
  team.
- Money/goods actions (refunds, sending invoices, replacement orders) should stay human-confirmed
  (e.g. via Telegram) until the classifier is trusted.
- Owner wants to refine sheet layout, dropdown stages, and number of dropdowns collaboratively.

Implementation notes for Phase 2:
- Add Google Sheets API scope to the OAuth (re-auth may be needed). Sheet data lives in Google,
  not on the server.
- Match incoming emails to existing cases by Gmail threadId (store threadId in the sheet row).
- Keep the same "only spend an LLM call when needed" discipline.
- Telegram: create bot via @BotFather (token), get chat ID via @userinfobot, store token+chatID
  in .env, send only on urgent classifications.

---

## 8. STATUS SUMMARY
- Phase 1 (classify + draft, 24/7 cron): BUILT, TESTED, LIVE. Confirmed creating real drafts in
  the owner's voice; correctly ignoring non-customer mail.
- Phase 2 (sheets + stages + Telegram): NOT STARTED. Spec seed above.
- Immediate watch items: keep the Anthropic API account funded; the running system depends on it.
