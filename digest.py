#!/usr/bin/env python3
"""Daily quantum computing news digest: RSS → Gemini → Gmail."""

from __future__ import annotations

import os
import re
import smtplib
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

import feedparser
import markdown
from google import genai
from google.genai import types

FEEDS = [
    ("arXiv quant-ph", "https://rss.arxiv.org/rss/quant-ph"),
    ("Phys.org Quantum Physics", "https://phys.org/rss-feed/physics-news/quantum-physics/"),
    ("Quantum Zeitgeist", "https://quantumzeitgeist.com/feed/"),
]

LOOKBACK = timedelta(hours=24)
MODEL = "gemini-3.6-flash"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
USER_AGENT = "QuantumDigest/1.0 (+https://github.com; daily RSS digest)"

SYSTEM_INSTRUCTION = """You are a specialized quantum computing intelligence analyst.
Your audience is researchers, engineers, and operators who need a concise daily brief.

From the provided items (already limited to the last 24 hours), curate the 3–5 most
impactful developments. Prioritize:
- hardware breakthroughs (qubits, error correction, cryogenics, control electronics)
- foundational papers and theoretical results
- algorithmic / software-stack updates
- industry, funding, and policy announcements with real technical weight

Ignore fluff, recycled press, and items only loosely related to quantum computing.

Write Markdown only (no HTML). Structure:
# Quantum Computing Digest — {date}

A one-sentence overview of the day's signal.

Then 3–5 items, each:
## Title
**Why it matters:** one sentence
**Summary:** 2–4 sentences of substance
**Source:** [publication or arXiv id](url)

If fewer than 3 items are truly high-impact, include fewer rather than padding.
End with a short "Also noted" bullet list only if leftover items are worth a mention.
"""


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _entry_datetime(entry: feedparser.FeedParserDict) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    return None


def _entry_summary(entry: feedparser.FeedParserDict, limit: int = 800) -> str:
    raw = (entry.get("summary") or entry.get("description") or "").strip()
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def fetch_recent_news() -> list[dict]:
    """Parse configured RSS feeds and keep entries from the last 24 hours."""
    cutoff = datetime.now(timezone.utc) - LOOKBACK
    seen_links: set[str] = set()
    items: list[dict] = []

    for source, url in FEEDS:
        parsed = feedparser.parse(url, agent=USER_AGENT)
        if parsed.bozo and not parsed.entries:
            print(f"Warning: failed to parse {source}: {parsed.bozo_exception}", file=sys.stderr)
            continue

        for entry in parsed.entries:
            published = _entry_datetime(entry)
            if published is None or published < cutoff:
                continue

            link = (entry.get("link") or "").strip()
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            dedupe_key = link or title.lower()
            if dedupe_key in seen_links:
                continue
            seen_links.add(dedupe_key)

            items.append(
                {
                    "source": source,
                    "title": title,
                    "link": link,
                    "published": published.isoformat(),
                    "summary": _entry_summary(entry),
                }
            )

    items.sort(key=lambda item: item["published"], reverse=True)
    return items


def _format_items_for_prompt(items: list[dict]) -> str:
    blocks = []
    for i, item in enumerate(items, start=1):
        blocks.append(
            f"{i}. [{item['source']}] {item['title']}\n"
            f"   Published: {item['published']}\n"
            f"   URL: {item['link']}\n"
            f"   Excerpt: {item['summary'] or '(none)'}"
        )
    return "\n\n".join(blocks)


def summarize_with_ai(items: list[dict]) -> str:
    """Ask Gemini to curate and summarize the day's most important items."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    api_key = _require_env("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    prompt = (
        f"Today's UTC date is {today}. Curate a digest from these {len(items)} items:\n\n"
        f"{_format_items_for_prompt(items)}"
    )

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION.format(date=today),
            temperature=0.3,
        ),
    )
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty summary.")
    return text


def _html_email(markdown_body: str) -> str:
    body_html = markdown.markdown(
        markdown_body,
        extensions=["extra", "sane_lists", "nl2br"],
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Quantum Computing Digest</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f4f5;padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="max-width:640px;width:100%;background:#ffffff;border-radius:8px;padding:28px 32px;color:#18181b;line-height:1.55;">
          <tr>
            <td>
              {body_html}
              <p style="margin-top:32px;font-size:12px;color:#71717a;">
                Automated daily digest. Generated with Gemini; sources linked above.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_email(subject: str, markdown_body: str) -> None:
    """Send an HTML email via Gmail SMTP (App Password)."""
    sender = _require_env("SENDER_EMAIL")
    password = _require_env("GMAIL_APP_PASS").replace(" ", "")
    receiver = _require_env("RECEIVER_EMAIL")

    html_body = _html_email(markdown_body)
    text_body = markdown_body

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = receiver
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.starttls(context=context)
        smtp.login(sender, password)
        smtp.sendmail(sender, [receiver], message.as_string())


def _quiet_day_markdown(items: list[dict]) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        f"# Quantum Computing Digest — {today}\n\n"
        "No new papers or articles were posted in the last 24 hours from the "
        "configured feeds (arXiv quant-ph, Phys.org Quantum Physics, Quantum Zeitgeist).\n\n"
        "The job ran successfully; there was simply nothing in the window to curate."
    )


def main() -> int:
    print("Fetching RSS feeds…")
    items = fetch_recent_news()
    print(f"Found {len(items)} item(s) in the last 24 hours.")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not items:
        body = _quiet_day_markdown(items)
        subject = f"Quantum Digest {today} — quiet day"
        print("No recent items; sending quiet-day notice.")
    else:
        print("Summarizing with Gemini…")
        body = summarize_with_ai(items)
        subject = f"Quantum Computing Digest — {today}"

    send_email(subject, body)
    print(f"Email sent to {os.environ.get('RECEIVER_EMAIL', '(unset)')}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 — surface any failure to Actions
        print(f"Digest failed: {exc}", file=sys.stderr)
        raise
