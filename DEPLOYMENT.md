# Deploying to a Hetzner Ubuntu Server

This guide walks you through getting the automation running on a fresh Ubuntu server with no prior setup.

---

## Prerequisites

You need:
- A Hetzner server running Ubuntu 22.04 or 24.04
- SSH access to that server
- Your `credentials.json` file from Google Cloud (see README.md step 2 if you haven't done this yet)
- Your Anthropic API key

---

## Part 1 — Connect to your server

On your local machine, open a terminal and SSH in:

```bash
ssh root@YOUR_SERVER_IP
```

Replace `YOUR_SERVER_IP` with the IP address shown in your Hetzner dashboard. Type `yes` if asked to confirm the fingerprint.

---

## Part 2 — Install Python and Git

Ubuntu 22.04/24.04 comes with Python 3, but you need pip and git:

```bash
apt update && apt upgrade -y
apt install -y python3-pip python3-venv git
```

Verify Python is installed:

```bash
python3 --version
```

You should see `Python 3.10.x` or higher.

---

## Part 3 — Get the code onto the server

```bash
git clone https://github.com/ascendibrand/support-automation.git
cd support-automation
```

---

## Part 4 — Create a Python virtual environment

A virtual environment keeps the project's dependencies isolated:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

You should see packages installing. When it finishes, your prompt will show `(venv)` at the start.

**Every time you SSH in and want to run something manually, re-activate the environment first:**

```bash
cd support-automation
source venv/bin/activate
```

---

## Part 5 — Upload your credentials.json

The server has no browser, so you can't download files from Google Cloud directly. Upload `credentials.json` from your local machine.

**On your local machine** (open a second terminal, don't close the SSH one):

```bash
scp /path/to/credentials.json root@YOUR_SERVER_IP:~/support-automation/credentials.json
```

Replace `/path/to/credentials.json` with the actual path on your computer (e.g. `~/Downloads/credentials.json`).

---

## Part 6 — Authorize support@ascend.store (no browser needed)

Run this on the server. It will print a URL instead of opening a browser:

```bash
cd ~/support-automation
source venv/bin/activate
python setup_auth.py
```

You'll see output like:

```
============================================================
Open this URL in a browser on your own PC:

https://accounts.google.com/o/oauth2/auth?...

Sign in with support@ascend.store (not your personal account).
After approving, Google will show you an authorization code.
============================================================

Paste the authorization code here and press Enter:
```

1. Copy the long URL and open it in a browser **on your own PC**
2. Sign in with `support@ascend.store`
3. Click Allow
4. Google will show you a short authorization code — copy it
5. Paste it back into the server terminal and press Enter

The script will confirm which account was authorized and save `token_support.json`.

---

## Part 7 — Set your Anthropic API key

Store the key in a file that the cron job will load:

```bash
echo "ANTHROPIC_API_KEY=sk-ant-YOUR-KEY-HERE" > ~/support-automation/.env
chmod 600 ~/support-automation/.env
```

Replace `sk-ant-YOUR-KEY-HERE` with your actual key. The `chmod 600` makes the file readable only by your user.

---

## Part 8 — Build the knowledge base

This scans your past replied threads and builds the RAG knowledge base:

```bash
cd ~/support-automation
source venv/bin/activate
python scripts/build_kb.py
```

It will print how many threads it found and save `kb.json`. This can take a minute or two depending on how many emails are in the inbox.

---

## Part 9 — Test run

Do a dry run first to make sure everything works before scheduling it:

```bash
cd ~/support-automation
source venv/bin/activate
export $(cat .env)
python orchestrate.py --dry-run
```

You should see threads being classified and draft previews printed. No changes are made to Gmail in dry-run mode.

If that looks good, do a live run:

```bash
python orchestrate.py
```

Check your Gmail inbox — threads should now have `Support/No Action` or `Support/Action Required` labels, and drafts should appear for action-required threads.

---

## Part 10 — Schedule with cron

Cron runs commands automatically on a schedule. You'll set up two jobs:

1. **orchestrate.py** — runs every 15 minutes to process new emails
2. **build_kb.py** — runs once a day at 3am to refresh the knowledge base

Open the cron editor:

```bash
crontab -e
```

If it asks which editor to use, type `1` and press Enter to pick nano.

Paste these two lines at the bottom of the file (everything after the `#` comments):

```
*/15 * * * * cd /root/support-automation && source venv/bin/activate && export $(cat .env) && python orchestrate.py >> logs/run.log 2>&1

0 3 * * * cd /root/support-automation && source venv/bin/activate && export $(cat .env) && python scripts/build_kb.py >> logs/kb.log 2>&1
```

Save and exit: press `Ctrl+X`, then `Y`, then `Enter`.

Create the logs directory so the log files have somewhere to go:

```bash
mkdir -p ~/support-automation/logs
```

Verify cron saved your jobs:

```bash
crontab -l
```

You should see both lines printed back.

---

## Part 11 — Verify it's running

Wait 15 minutes, then check the log:

```bash
tail -50 ~/support-automation/logs/run.log
```

You should see output like:

```
=== Support Email Automation ===
Authorized as: support@ascend.store
Found 3 unhandled threads.
[1/3] Order #1234 question
  → No Action (last message is from support)
[2/3] Where is my package?
  → Action Required (customer asking about shipping)
  Draft created: r123456789
...
```

If the log file is empty or missing, the cron job hasn't run yet — wait a bit longer or check for errors with:

```bash
grep CRON /var/log/syslog | tail -20
```

---

## Keeping the token fresh

The OAuth token auto-refreshes itself as long as the automation runs at least once every few months. If you ever see an authentication error in the logs, just re-run `setup_auth.py` on your local machine and re-upload `token_support.json`.

---

## Refreshing the knowledge base manually

If you want to rebuild the KB outside of the 3am schedule (e.g. after a burst of support replies):

```bash
cd ~/support-automation
source venv/bin/activate
export $(cat .env)
python scripts/build_kb.py
```

---

## Quick reference

| Task | Command |
|---|---|
| Check recent logs | `tail -50 ~/support-automation/logs/run.log` |
| Run manually | `cd ~/support-automation && source venv/bin/activate && export $(cat .env) && python orchestrate.py` |
| Dry run | same as above but add `--dry-run` |
| Rebuild KB | same as above but `python scripts/build_kb.py` |
| Edit cron schedule | `crontab -e` |
| View cron jobs | `crontab -l` |
