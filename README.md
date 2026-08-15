# Quantum Digest

Zero-cost daily quantum computing news brief. GitHub Actions pulls RSS feeds (arXiv quant-ph, Phys.org Quantum Physics, Quantum Zeitgeist), filters to the last 24 hours, has Gemini curate the top developments, and emails you HTML via Gmail SMTP.

## How it works

1. Cron (or **Run workflow**) starts `.github/workflows/daily_digest.yml`.
2. `digest.py` fetches feeds, keeps entries from the past 24 hours, and calls `gemini-3.6-flash`.
3. Markdown is converted to HTML and sent with `smtplib` through Gmail.

Schedule: `0 12 * * *` (12:00 UTC ≈ 7:00 AM EST / 8:00 AM EDT). Change the cron in the workflow file if you want a different time. GitHub cron can drift by a few minutes.

## Secrets (put personal info here — never in the repo)

Do **not** commit API keys, emails, or the Gmail app password. `.env` is gitignored. Production values live only in **GitHub Actions secrets**.

1. Open the repo on GitHub → **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret** and add each of these **exact** names:

| Secret name | What to paste |
| --- | --- |
| `GEMINI_API_KEY` | Google AI Studio API key |
| `SENDER_EMAIL` | The Gmail address that sends the digest (must match the App Password account) |
| `GMAIL_APP_PASS` | 16-character Gmail App Password (spaces optional; the script strips them) |
| `RECEIVER_EMAIL` | Inbox that should receive the digest (can be the same as sender) |

Those names are what the workflow maps into environment variables. If a name is wrong, the job will fail with a missing-variable error.

### Gemini API key (free tier)

1. Go to [Google AI Studio](https://aistudio.google.com/apikey).
2. Create an API key for a Google account.
3. Store it as `GEMINI_API_KEY`. The script uses `gemini-3.6-flash` on the Gemini Developer API (AI Studio free tier), not Vertex AI billing. Newer Gemini keys cannot call retired `gemini-2.5-flash`.

Free-tier limits can change; if a run fails with quota/429, wait and retry, or check [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).

### Gmail App Password

Regular Gmail login passwords will **not** work with SMTP.

1. Turn on [2-Step Verification](https://myaccount.google.com/signinoptions/twosv) on the sending Google account.
2. Open [App passwords](https://myaccount.google.com/apppasswords).
3. Create an app password (e.g. name it “Quantum Digest”).
4. Copy the 16-character password into `GMAIL_APP_PASS`.
5. Set `SENDER_EMAIL` to that same Gmail address.

Workspace/Google Workspace accounts may need the admin to allow App Passwords.

## Manual test

After secrets are saved:

1. **Actions** → **Daily Quantum Digest** → **Run workflow**.
2. Confirm the job is green and the email arrives (check spam the first time).

If there were no new items in 24 hours, you still get a short “quiet day” email so you know the job ran.

## Local run (optional)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export GEMINI_API_KEY="…"
export SENDER_EMAIL="you@gmail.com"
export GMAIL_APP_PASS="xxxx xxxx xxxx xxxx"
export RECEIVER_EMAIL="you@gmail.com"

python digest.py
```

Use exports or a local `.env` file that you never commit. Do not put secrets in `digest.py` or the workflow YAML.

## Files

- `digest.py` — fetch, summarize, send
- `requirements.txt` — `google-genai`, `feedparser`, `markdown`, `requests`
- `.github/workflows/daily_digest.yml` — daily cron + `workflow_dispatch`
