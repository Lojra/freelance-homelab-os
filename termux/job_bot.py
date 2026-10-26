#!/usr/bin/env python3
"""
Lightweight 24/7 Hardware Scout & Fiverr IMAP Listener for Android/Termux.
Operates purely locally without AI models or heavy browser automation.
- High-speed active project polling via official Freelancer.com REST API
- Evaluates projects using local keyword matching (KiCad, PCB, 3D Print, Enclosures, ESP32, etc.)
- Strict blacklist filtering (Trading, Forex, Crypto, 4-layer, RF design, Mains voltage, etc.)
- Saves matched job queue to www/matched_jobs.json with 'pending' status
- Zero-Ban Fiverr IMAP Listener: checks imap.gmail.com for @fiverr.com client inquiries & briefs
- Saves Fiverr inquiries to www/fiverr_inbox.json and alerts Discord with [FIVERR] badge
- Battery Thermal Watchdog (>39.0°C alert) & ESP32-C3 Pi-hole node health watchdog
- Generates stats.json for the Homelab Command Center dashboard
"""

import os
import sys
import json
import re
import html
import time
import logging
import gc
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timezone
import requests

# Lightweight logging configuration
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("HomelabScout")

# Base paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_JOBS_FILE = os.path.join(BASE_DIR, "seen_jobs.json")
SEEN_MSGS_FILE = os.path.join(BASE_DIR, "seen_messages.json")
SEEN_FIVERR_FILE = os.path.join(BASE_DIR, "seen_fiverr_emails.json")
ENV_FILE = os.path.join(BASE_DIR, ".env")
LOG_FILE = os.path.join(BASE_DIR, "job_bot.log")
WWW_DIR = os.path.join(BASE_DIR, "www")
STATS_JSON = os.path.join(WWW_DIR, "stats.json")
MATCHED_JOBS_JSON = os.path.join(WWW_DIR, "matched_jobs.json")
FIVERR_INBOX_JSON = os.path.join(WWW_DIR, "fiverr_inbox.json")
DISMISSED_FIVERR_FILE = os.path.join(WWW_DIR, "dismissed_fiverr.json")
TUNNEL_URL_FILE = os.path.join(WWW_DIR, "tunnel_url.txt")
LOG_SYMLINK = os.path.join(WWW_DIR, "job_bot.log")

# Hardware & 3D Print niche keywords
TARGET_KEYWORDS = [
    "kicad", "pcb", "schematic", "gerber", "breadboard", "fritzing",
    "breakout board", "carrier board", "enclosure", "3d print",
    "3d-printable", "stl", "step", "case design", "esp32", "arduino",
    "sensor board", "relay board", "2-layer", "bom"
]

# Strict blacklist keywords (titles or descriptions containing these are rejected)
BLACKLIST_KEYWORDS = [
    "trading", "mt4", "mt5", "metatrader", "forex", "crypto",
    "4-layer", "4 layer", "6-layer", "rf design", "antenna",
    "high-speed", "mains voltage", "ac power", "web scraping",
    "wordpress", "shopify"
]

DEFAULT_VERCEL_APP_URL = "https://your-homelab-app.vercel.app"
FREELANCER_API_BASE = "https://www.freelancer.com/api"


def load_env_file():
    """Load environment variables from .env file if present."""
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and not os.environ.get(key):
                        os.environ[key] = val
        except Exception as e:
            logger.warning(f"Error loading {ENV_FILE}: {e}")


def get_auth_headers(token: str) -> dict:
    """Return standard headers for Freelancer.com OAuth API."""
    return {
        "freelancer-oauth-v1": token,
        "Content-Type": "application/json",
        "User-Agent": "HomelabTermuxScout/1.0",
    }


def load_id_set(filepath: str) -> set:
    """Load previously processed IDs to prevent duplicates."""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
                elif isinstance(data, dict):
                    return set(data.keys())
        except Exception as e:
            logger.warning(f"Error reading {filepath}: {e}")
    return set()


def save_id_set(filepath: str, id_set: set, max_items: int = 500):
    """Save processed IDs, capped to prevent state file growth."""
    try:
        capped = list(id_set)[-max_items:]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(capped, f)
    except Exception as e:
        logger.error(f"Error saving {filepath}: {e}")


def load_matched_jobs() -> list:
    """Load structured matched jobs queue."""
    if os.path.exists(MATCHED_JOBS_JSON):
        try:
            with open(MATCHED_JOBS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            logger.warning(f"Error reading {MATCHED_JOBS_JSON}: {e}")
    return []


def save_matched_jobs(jobs: list, max_items: int = 200):
    """Save structured matched jobs queue."""
    try:
        os.makedirs(WWW_DIR, exist_ok=True)
        capped = jobs[-max_items:]
        with open(MATCHED_JOBS_JSON, "w", encoding="utf-8") as f:
            json.dump(capped, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving {MATCHED_JOBS_JSON}: {e}")


def load_fiverr_inbox() -> list:
    """Load structured Fiverr client inquiry inbox."""
    if os.path.exists(FIVERR_INBOX_JSON):
        try:
            with open(FIVERR_INBOX_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            logger.warning(f"Error reading {FIVERR_INBOX_JSON}: {e}")
    return []


def save_fiverr_inbox(inbox: list, max_items: int = 100):
    """Save structured Fiverr client inquiry inbox."""
    try:
        os.makedirs(WWW_DIR, exist_ok=True)
        capped = inbox[-max_items:]
        with open(FIVERR_INBOX_JSON, "w", encoding="utf-8") as f:
            json.dump(capped, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving {FIVERR_INBOX_JSON}: {e}")


def get_app_url() -> str:
    """Retrieve the frontend URL."""
    return os.environ.get("VERCEL_APP_URL", DEFAULT_VERCEL_APP_URL).rstrip("/")


def clean_text(text: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def send_discord_notification(webhook_url: str, title: str, description: str, fields: list = None, color: int = 0x10B981, url: str = None):
    """Send a rich Discord Embed notification."""
    if not webhook_url:
        logger.warning("Discord webhook URL not configured.")
        return

    embed = {
        "title": title,
        "description": description,
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {
            "text": "Homelab OS Command Center // Autonomous Scout",
        }
    }
    if url:
        embed["url"] = url
    if fields:
        embed["fields"] = fields

    payload = {
        "username": "Homelab Hardware Scout",
        "embeds": [embed]
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            logger.info(f"Discord notification sent: {title}")
        else:
            logger.warning(f"Discord webhook error {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Failed to dispatch Discord webhook: {e}")


def check_battery_thermal_watchdog(webhook_url: str):
    """Monitor battery temperature and capacity on Android device."""
    temp_c = None
    capacity = None
    try:
        temp_path = "/sys/class/power_supply/battery/temp"
        cap_path = "/sys/class/power_supply/battery/capacity"
        if os.path.exists(temp_path):
            with open(temp_path, "r", encoding="utf-8") as f:
                raw_temp = int(f.read().strip())
                temp_c = raw_temp / 10.0 if raw_temp > 100 else float(raw_temp)
        if os.path.exists(cap_path):
            with open(cap_path, "r", encoding="utf-8") as f:
                capacity = int(f.read().strip())
    except Exception as e:
        logger.warning(f"Error reading battery thermal metrics: {e}")

    if temp_c is not None:
        logger.info(f"Battery Thermal Check: {temp_c}°C (Capacity: {capacity}%)")
        if temp_c >= 39.0 and webhook_url:
            logger.warning(f"🔥 [THERMAL WARNING] Battery temp {temp_c}°C exceeds 39.0°C limit!")
            fields = [
                {"name": "Current Temperature", "value": f"**{temp_c}°C**", "inline": True},
                {"name": "Battery Level", "value": f"{capacity}%", "inline": True},
                {"name": "Watchdog Limit", "value": "39.0°C", "inline": True},
                {"name": "Recommendation", "value": "Reduce CPU load or unplug charger to avoid thermal throttling.", "inline": False},
            ]
            send_discord_notification(
                webhook_url=webhook_url,
                title="🔥 [THERMAL WARNING] Battery Exceeds 39.0°C!",
                description=f"Device battery temperature reached **{temp_c}°C** (Battery Level: {capacity}%). Thermal watchdog triggered.",
                fields=fields,
                color=0xEF4444,
            )


def check_esp32_pihole_watchdog(webhook_url: str):
    """Monitor ESP32-C3 Pi-hole node health via HTTP port 80."""
    ip = os.environ.get("ESP32_PIHOLE_IP", "192.168.1.50")
    port = os.environ.get("ESP32_PIHOLE_PORT", "80")
    url = f"http://{ip}:{port}"
    state_file = os.path.join(BASE_DIR, "esp32_watchdog_state.json")
    state = {"consecutive_failures": 0, "last_alert_sent": False}
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            pass

    is_alive = False
    try:
        r = requests.get(url, timeout=3.0)
        if r.status_code == 200:
            is_alive = True
    except Exception:
        is_alive = False

    if is_alive:
        if state.get("consecutive_failures", 0) > 0:
            logger.info(f"✅ ESP32-C3 Pi-hole node ({url}) is back ONLINE.")
            if state.get("last_alert_sent", False) and webhook_url:
                send_discord_notification(
                    webhook_url=webhook_url,
                    title="✅ [ESP32 PI-HOLE RECOVERED] DNS Node Online",
                    description=f"The ESP32-C3 Pi-hole DNS ad-blocker node at **{url}** is back online and responding.",
                    fields=[
                        {"name": "Target Node", "value": f"`{ip}:{port}`", "inline": True},
                        {"name": "Status", "value": "Operational (HTTP 200)", "inline": True},
                    ],
                    color=0x10B981,
                )
        state["consecutive_failures"] = 0
        state["last_alert_sent"] = False
        logger.info(f"ESP32 Pi-hole Check: {url} is ONLINE (HTTP 200)")
    else:
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        fail_count = state["consecutive_failures"]
        logger.warning(f"⚠️ ESP32-C3 Pi-hole node ({url}) unreachable (failures: {fail_count})")
        if fail_count >= 2 and not state.get("last_alert_sent", False):
            if webhook_url:
                logger.warning("🚨 [ESP32 PI-HOLE OFFLINE] Sending Discord alert...")
                send_discord_notification(
                    webhook_url=webhook_url,
                    title="🚨 [ESP32 PI-HOLE OFFLINE] DNS Node Unreachable!",
                    description=f"The ESP32-C3 Pi-hole DNS ad-blocker node at **{url}** failed {fail_count} consecutive health checks.",
                    fields=[
                        {"name": "Target Node", "value": f"`{ip}:{port}`", "inline": True},
                        {"name": "Consecutive Failures", "value": str(fail_count), "inline": True},
                        {"name": "Status", "value": "Offline / HTTP Unresponsive", "inline": True},
                    ],
                    color=0xEF4444,
                )
                state["last_alert_sent"] = True

    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save {state_file}: {e}")


def poll_and_scout_jobs(token: str, webhook_url: str):
    """Poll active Freelancer projects and evaluate keyword matches."""
    seen_jobs = load_id_set(SEEN_JOBS_FILE)
    matched_jobs_list = load_matched_jobs()
    existing_matched_ids = {j["project_id"] for j in matched_jobs_list if "project_id" in j}

    endpoint = f"{FREELANCER_API_BASE}/projects/0.1/projects/active/?limit=30&full_description=true&job_details=true"
    headers = get_auth_headers(token)

    try:
        resp = requests.get(endpoint, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.error(f"Freelancer API error {resp.status_code}: {resp.text}")
            return

        data = resp.json()
        projects = data.get("result", {}).get("projects", [])
        logger.info(f"Retrieved {len(projects)} active projects from Freelancer.")

        for p in projects:
            p_id = p.get("id")
            if not p_id or p_id in seen_jobs:
                continue

            seen_jobs.add(p_id)

            title = p.get("title", "")
            raw_desc = p.get("description", "") or p.get("preview_description", "")
            desc = clean_text(raw_desc)
            skills = [j.get("name", "") for j in p.get("jobs", [])]

            combined_text = f"{title}\n{desc}\n{' '.join(skills)}".lower()

            # 1. Blacklist Check
            has_blacklisted = False
            for b_kw in BLACKLIST_KEYWORDS:
                if re.search(r"\b" + re.escape(b_kw) + r"\b", combined_text, re.I):
                    has_blacklisted = True
                    break

            if has_blacklisted:
                continue

            # 2. Target Keyword Match
            matched_kw = []
            for kw in TARGET_KEYWORDS:
                if kw == "2-layer":
                    if re.search(r"\b2[- ]layer\b", combined_text, re.I):
                        matched_kw.append(kw)
                elif kw == "step":
                    if re.search(r"(?:\.step\b|\bstep\s+(?:file|model|format|cad|3d|export)\b|\b(?:cad|3d|export)\s+step\b)", combined_text, re.I):
                        matched_kw.append(kw)
                elif kw in ("stl", "bom", "pcb"):
                    if re.search(r"\b" + re.escape(kw) + r"\b", combined_text, re.I):
                        matched_kw.append(kw)
                elif " " in kw or "-" in kw:
                    if kw in combined_text:
                        matched_kw.append(kw)
                else:
                    if re.search(r"\b" + re.escape(kw) + r"\b", combined_text, re.I):
                        matched_kw.append(kw)

            if not matched_kw:
                continue

            # Project details
            currency = p.get("currency", {})
            curr_code = currency.get("code", "USD")
            curr_sign = currency.get("sign", "$")
            budget = p.get("budget", {})
            min_b = budget.get("minimum")
            max_b = budget.get("maximum")

            budget_str = f"{curr_sign}{min_b} - {curr_sign}{max_b} {curr_code}" if min_b and max_b else "Not specified"
            seo_url = p.get("seo_url")
            project_url = f"https://www.freelancer.com/projects/{seo_url}" if seo_url else f"https://www.freelancer.com/projects/{p_id}"

            job_entry = {
                "project_id": p_id,
                "title": title,
                "url": project_url,
                "description": desc,
                "min_budget": min_b,
                "max_budget": max_b,
                "currency": curr_code,
                "currency_sign": curr_sign,
                "budget_display": budget_str,
                "skills": skills,
                "matched_keywords": matched_kw,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "bid_status": "pending",
            }

            if p_id not in existing_matched_ids:
                matched_jobs_list.append(job_entry)
                existing_matched_ids.add(p_id)
                logger.info(f"⚡ [MATCH FOUND] #{p_id}: {title} (Keywords: {', '.join(matched_kw)})")

                # Dispatch Discord Alert with Action Link to Command Center Web App
                app_link = get_app_url()
                fields = [
                    {"name": "💰 Budget", "value": f"**{budget_str}**", "inline": True},
                    {"name": "🎯 Keywords", "value": ", ".join(f"`{k}`" for k in matched_kw), "inline": True},
                    {"name": "🛠️ Skills", "value": ", ".join(skills[:5]) if skills else "N/A", "inline": False},
                    {"name": "📝 Snippet", "value": (desc[:200] + "...") if len(desc) > 200 else desc, "inline": False},
                    {"name": "⚡ Interactive Action", "value": f"[**Open Swipe Deck to Bid ➔**]({app_link})", "inline": False},
                ]
                send_discord_notification(
                    webhook_url=webhook_url,
                    title=f"⚡ [NEW HARDWARE LEAD] {title}",
                    description=f"Scouted on Freelancer. Review and swipe to bid directly from your Command Center.",
                    fields=fields,
                    color=0x10B981,
                    url=project_url,
                )

        save_id_set(SEEN_JOBS_FILE, seen_jobs)
        save_matched_jobs(matched_jobs_list)

    except Exception as e:
        logger.error(f"Error polling jobs: {e}")


def write_stats_json():
    """Update stats.json for the dashboard."""
    try:
        seen_jobs = load_id_set(SEEN_JOBS_FILE)
        seen_msgs = load_id_set(SEEN_MSGS_FILE)
        matched_jobs = load_matched_jobs()
        fiverr_inbox = load_fiverr_inbox()

        pending_jobs = [j for j in matched_jobs if j.get("bid_status") == "pending"]
        bidded_jobs = [j for j in matched_jobs if j.get("bid_status") == "bid_sent"]
        dismissed_jobs = [j for j in matched_jobs if j.get("bid_status") == "dismissed"]
        fiverr_unread = [m for m in fiverr_inbox if m.get("status") == "unread"]

        stats = {
            "total_processed_jobs": len(seen_jobs),
            "total_scouted_matches": len(matched_jobs),
            "pending_matches": len(pending_jobs),
            "bids_sent": len(bidded_jobs),
            "dismissed_jobs": len(dismissed_jobs),
            "total_processed_messages": len(seen_msgs),
            "fiverr_inbox_count": len(fiverr_inbox),
            "fiverr_unread_count": len(fiverr_unread),
            "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_run_iso": datetime.now(timezone.utc).isoformat(),
            "target_keywords": TARGET_KEYWORDS,
            "blacklist_keywords": BLACKLIST_KEYWORDS,
            "mode": "Homelab Hardware Scout & Fiverr Listener",
            "status": "online",
            "app_url": get_app_url(),
        }
        with open(STATS_JSON, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to write stats.json: {e}")


def run_cycle():
    """Main execution cycle run by cron."""
    start_time = time.time()
    load_env_file()

    token = os.environ.get("FREELANCER_OAUTH_TOKEN")
    discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL")

    # Watchdogs
    check_battery_thermal_watchdog(discord_webhook)
    check_esp32_pihole_watchdog(discord_webhook)

    if not token:
        logger.warning("FREELANCER_OAUTH_TOKEN not set. Running in standby mode.")
        write_stats_json()
        return

    logger.info("Starting Hardware Scout Cycle...")
    poll_and_scout_jobs(token, discord_webhook)
    write_stats_json()

    elapsed = round(time.time() - start_time, 2)
    logger.info(f"Hardware scout cycle finished cleanly in {elapsed}s.")
    gc.collect()


if __name__ == "__main__":
    run_cycle()
