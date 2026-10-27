#!/usr/bin/env python3
"""
Dedicated Zero-Ban Fiverr IMAP Email Listener for Samsung J5 / Termux.
Runs as an independent staggered cron job (every 10 minutes) to eliminate CPU spikes.
"""

import os
import sys
import json
import re
import time
import logging
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timezone
import requests

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [FiverrBot] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("FiverrBot")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WWW_DIR = os.path.join(BASE_DIR, "www")
ENV_FILE = os.path.join(BASE_DIR, ".env")
FIVERR_INBOX_JSON = os.path.join(WWW_DIR, "fiverr_inbox.json")
SEEN_FIVERR_FILE = os.path.join(BASE_DIR, "seen_fiverr_emails.json")
DISMISSED_FIVERR_FILE = os.path.join(WWW_DIR, "dismissed_fiverr.json")
TUNNEL_URL_FILE = os.path.join(WWW_DIR, "tunnel_url.txt")

DEFAULT_VERCEL_APP_URL = "https://freelancer-command-center-chi.vercel.app"


def load_env_file():
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and not os.environ.get(k):
                        os.environ[k] = v
        except Exception as e:
            logger.warning(f"Error loading {ENV_FILE}: {e}")


def load_id_set(filepath: str) -> set:
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
                elif isinstance(data, dict):
                    return set(data.keys())
        except Exception:
            pass
    return set()


def save_id_set(filepath: str, id_set: set, max_items: int = 500):
    try:
        capped = list(id_set)[-max_items:]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(capped, f)
    except Exception as e:
        logger.error(f"Error saving {filepath}: {e}")


def load_fiverr_inbox() -> list[dict]:
    if os.path.exists(FIVERR_INBOX_JSON):
        try:
            with open(FIVERR_INBOX_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    return []


def save_fiverr_inbox(inbox: list[dict], max_items: int = 50):
    try:
        os.makedirs(WWW_DIR, exist_ok=True)
        with open(FIVERR_INBOX_JSON, "w", encoding="utf-8") as f:
            json.dump(inbox[-max_items:], f, indent=2)
    except Exception as e:
        logger.error(f"Error saving {FIVERR_INBOX_JSON}: {e}")


def get_app_url() -> str:
    if os.path.exists(TUNNEL_URL_FILE):
        try:
            with open(TUNNEL_URL_FILE, "r", encoding="utf-8") as f:
                tunnel = f.read().strip()
                if tunnel.startswith("https://"):
                    return tunnel
        except Exception:
            pass
    return os.environ.get("VERCEL_APP_URL", DEFAULT_VERCEL_APP_URL)


def send_discord_alert(webhook_url: str, title: str, description: str, fields: list[dict] = None, color: int = 0x8B5CF6, url: str = None):
    if not webhook_url:
        return
    embed = {
        "title": title[:256],
        "description": description[:2048],
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Fiverr IMAP Service // Samsung J5 Node"}
    }
    if url:
        embed["url"] = url
    if fields:
        embed["fields"] = fields
    payload = {"username": "Fiverr Client Desk", "embeds": [embed]}
    try:
        requests.post(webhook_url, json=payload, timeout=8)
    except Exception as e:
        logger.warning(f"Discord dispatch error: {e}")


def poll_fiverr():
    load_env_file()
    email_user = os.environ.get("EMAIL_ADDRESS")
    email_pass = os.environ.get("EMAIL_APP_PASSWORD")
    imap_host = os.environ.get("IMAP_SERVER", "imap.gmail.com")
    discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL")

    if not email_user or not email_pass:
        logger.info("EMAIL_ADDRESS or EMAIL_APP_PASSWORD missing. Skipping.")
        return

    inbox = load_fiverr_inbox()
    seen_ids = load_id_set(SEEN_FIVERR_FILE)
    dismissed_ids = load_id_set(DISMISSED_FIVERR_FILE)

    logger.info(f"Connecting to {imap_host} as {email_user}...")
    try:
        mail = imaplib.IMAP4_SSL(imap_host, 993, timeout=12)
        mail.login(email_user, email_pass)
        mail.select("INBOX")

        status, messages = mail.search(None, '(FROM "fiverr.com")')
        if status != "OK" or not messages[0]:
            logger.info("Zero Fiverr emails in inbox.")
            mail.logout()
            return

        msg_ids = messages[0].split()
        recent_ids = msg_ids[-10:]

        new_seen = set(seen_ids)
        new_inquiries = 0

        for mid in reversed(recent_ids):
            mid_str = mid.decode("utf-8")
            if mid_str in seen_ids or mid_str in dismissed_ids:
                continue

            res, msg_data = mail.fetch(mid, "(RFC822)")
            if res != "OK":
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            subject_raw, encoding = decode_header(msg.get("Subject", ""))[0]
            if isinstance(subject_raw, bytes):
                subject = subject_raw.decode(encoding if encoding else "utf-8", errors="replace")
            else:
                subject = str(subject_raw)

            sub_lower = subject.lower()
            if not any(k in sub_lower for k in ["message", "custom offer", "brief", "order", "inquiry", "buyer"]):
                new_seen.add(mid_str)
                continue

            sender = "Fiverr Client"
            sender_match = re.search(r"(?:messages?\s+from|from)\s+([a-zA-Z0-9_\-]+)", subject, re.I)
            if not sender_match:
                sender_match = re.search(r"([a-zA-Z0-9_\-]+)\s+(?:sent you|requested|placed)", subject, re.I)
            if sender_match:
                extracted = sender_match.group(1).strip()
                if extracted.lower() not in ["a", "the", "fiverr"]:
                    sender = extracted

            body_text = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ctype = part.get_content_type()
                    if ctype == "text/plain":
                        body_text = part.get_payload(decode=True).decode("utf-8", errors="replace")
                        break
                    elif ctype == "text/html" and not body_text:
                        body_text = part.get_payload(decode=True).decode("utf-8", errors="replace")
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body_text = payload.decode("utf-8", errors="replace")

            snippet = re.sub(r"<[^>]+>", " ", body_text)
            snippet = re.sub(r"\s+", " ", snippet).strip()[:240]

            inbox_item = {
                "id": mid_str,
                "sender": sender,
                "subject": subject,
                "snippet": snippet or "Client inquiry received on Fiverr.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "fiverr_link": f"https://www.fiverr.com/inbox/{sender}" if sender != "Fiverr Client" else "https://www.fiverr.com/inbox",
                "status": "unread",
                "inquiry_type": "Custom Offer" if "offer" in sub_lower else "Direct Message",
            }

            inbox.insert(0, inbox_item)
            new_seen.add(mid_str)
            new_inquiries += 1

            logger.info(f"📩 New Fiverr message: '{subject}' from @{sender}")

            if discord_webhook:
                dash_url = f"{get_app_url()}?view=fiverr"
                fields = [
                    {"name": "👤 Sender", "value": f"**@{sender}**", "inline": True},
                    {"name": "📂 Type", "value": inbox_item["inquiry_type"], "inline": True},
                    {"name": "💬 Snippet", "value": snippet[:180] if snippet else "New inquiry", "inline": False},
                ]
                send_discord_alert(
                    discord_webhook,
                    f"📬 NEW FIVERR INQUIRY: @{sender}",
                    f"**{subject}**\n[Open in Homelab Dashboard]({dash_url}) • [Reply on Fiverr]({inbox_item['fiverr_link']})",
                    fields=fields,
                    color=0x8B5CF6,
                    url=dash_url
                )

        save_id_set(SEEN_FIVERR_FILE, new_seen)
        save_fiverr_inbox(inbox)
        mail.close()
        mail.logout()
        logger.info(f"Fiverr check complete. {new_inquiries} new inquiries processed.")

    except Exception as e:
        logger.error(f"Fiverr check error: {e}")


if __name__ == "__main__":
    poll_fiverr()
