# Support Email Automation

Automates triage and draft replies for `support@ascend.store` using a 3-layer architecture:

- **Layer 1 — Directives** (`directives/`): System prompts for classification and drafting
- **Layer 2 — Execution scripts** (`scripts/`): Gmail API wrapper, KB builder, RAG retriever
- **Layer 3 — Orchestration** (`orchestrate.py`): Claude calls, decision logic, labeling, draft creation

## How it works

For each unhandled inbox thread:

1. **Hard rule**: if the last message in the thread is from support, label "Support/No Action" and skip (no LLM call)
2. **Classify** with Claude Haiku (`claude-haiku-4-5`): "No Action" or "Action Required"
3. **Apply Gmail label**: `Support/No Action` or `Support/Action Required`
4. **Draft reply** (Action Required only): RAG retrieves past answers → Claude Haiku (`claude-haiku-4-5`) writes a casual draft → saved as Gmail draft for manual review

Drafts are never sent automatically.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Google Cloud credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create or select a project
3. Enable the Gmail API
4. Create OAuth 2.0 credentials (Desktop app type)
5. Download and save as `credentials.json` in this directory

### 3. Authorize support@ascend.store

```bash
python setup_auth.py
```

Sign in with `support@ascend.store` (not your personal account). This saves `token_support.json`.

### 4. Set your Anthropic API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 5. Build the knowledge base

Scans replied threads to extract Q&A pairs for RAG:

```bash
python scripts/build_kb.py
```

Saves `kb.json`. Re-run periodically to keep it fresh.

### 6. Run the automation

```bash
# Normal run (processes up to 50 threads)
python orchestrate.py

# Dry run — classify and preview drafts without touching Gmail
python orchestrate.py --dry-run

# Process more threads
python orchestrate.py --max-threads 100
```

## Files

```
support-automation/
├── credentials.json        # Google OAuth credentials (you create this)
├── token_support.json      # OAuth token (auto-created by setup_auth.py)
├── kb.json                 # Knowledge base (auto-created by build_kb.py)
├── setup_auth.py           # One-time OAuth setup
├── orchestrate.py          # Main script
├── requirements.txt
├── directives/
│   ├── classify.txt        # Classification system prompt
│   └── draft.txt           # Drafting system prompt
└── scripts/
    ├── gmail_client.py     # Gmail API wrapper
    ├── build_kb.py         # Knowledge base builder
    └── rag.py              # TF-IDF retriever with recency decay
```

## RAG details

- Pure stdlib TF-IDF (no external embedding dependencies)
- Recency decay: `score = tfidf_similarity × exp(-0.005 × days_old)`
  - 90 days old → 64% of a fresh score
  - 1 year old → 16% of a fresh score
- Retrieves all outbound replies per thread (not just first/last)

## Scheduling

Run on a cron or scheduler. Example — every 15 minutes:

```
*/15 * * * * cd /path/to/support-automation && ANTHROPIC_API_KEY=sk-ant-... python orchestrate.py >> logs/run.log 2>&1
```

Rebuild the KB daily:

```
0 3 * * * cd /path/to/support-automation && python scripts/build_kb.py >> logs/kb.log 2>&1
```
