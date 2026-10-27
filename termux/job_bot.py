#!/usr/bin/env python3
"""
Lightweight Freelancer.com 24/7 Hardware & 3D Case Scout + Fiverr IMAP Listener for Android/Termux.
Operates purely locally on Samsung J5 without AI models or browser automation.
- Auto-syncs hardware profile skills with Freelancer.com API
- Strict 2-Layer Niche Filtering (Requires >= 1 Primary Hardware Keyword; Blacklists software/trading/mains/multi-layer)
- Live Currency Conversion to USD ($) with API rates + fallback table
- Dynamic Multi-Paragraph Proposal Generator tailored to PCB, 3D Case, or Combined Hardware
- 2-Tier Smart Auto-Bidder:
    * Tier 1 ($15 - $65 USD fixed): Immediate automatic bid submission + quiet Discord alert
    * Tier 2 (> $65 USD or hourly or error): Routed to 'needs_confirmation' queue + urgent Discord ping
- Zero-Ban Fiverr IMAP Listener: scans imap.gmail.com for @fiverr.com client inquiries & briefs
- Hardware Thermal & ESP32-C3 Pi-hole Watchdogs
- Generates stats.json and matched_jobs.json for the Homelab Command Center
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
import urllib.parse

# Lightweight logging configuration
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("HardwareScout")

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
FREELANCER_MESSAGES_JSON = os.path.join(WWW_DIR, "freelancer_messages.json")
TUNNEL_URL_FILE = os.path.join(WWW_DIR, "tunnel_url.txt")
LOG_SYMLINK = os.path.join(WWW_DIR, "job_bot.log")
PROPOSAL_TEMPLATES_FILE = os.path.join(BASE_DIR, "proposal_templates.json")

# Core Hardware Skill IDs on Freelancer.com
# 43: Electronics, 76: Circuit Design, 111: Microcontroller, 265: PCB Layout,
# 394: Electrical Engineering, 440: Solidworks, 612: Arduino, 630: Product Design,
# 1347: KiCad, 1657: 3D Printing / Prototyping
HARDWARE_SKILL_IDS = [43, 76, 111, 265, 394, 440, 612, 630, 1347, 1657]

# Layer 1: Primary Hardware Design Keywords (Must contain at least ONE)
PRIMARY_HARDWARE_KEYWORDS = [
    "kicad", "pcb", "schematic", "gerber", "breadboard", "fritzing",
    "breakout board", "carrier board", "enclosure", "3d print",
    "3d-printable", "stl", "step", "case design", "2-layer", "sensor board"
]

# Layer 2: Secondary Context Keywords (Bonus context only, NOT standalone triggers)
SECONDARY_CONTEXT_KEYWORDS = [
    "esp32", "arduino", "relay board", "bom", "stm32", "firmware",
    "iot", "microcontroller", "embedded", "hardware", "circuit"
]

# Strict Blacklist Keywords (Any match in title or description -> reject job)
BLACKLIST_KEYWORDS = [
    "trading", "mt4", "mt5", "metatrader", "forex", "crypto",
    "4-layer", "4 layer", "6-layer", "8-layer", "rf design", "antenna",
    "high-speed", "mains", "220v", "110v", "ac power",
    "wordpress", "shopify", "mobile app", "ios", "react native",
    "unity", "unreal", "fpga", "verilog"
]

# Fallback Currency Exchange Rates to USD ($)
FALLBACK_USD_RATES = {
    "USD": 1.0,
    "EUR": 1.08,    # 1 EUR = ~1.08 USD
    "GBP": 1.30,    # 1 GBP = ~1.30 USD
    "AUD": 0.65,    # 1 AUD = ~0.65 USD
    "CAD": 0.72,    # 1 CAD = ~0.72 USD
    "INR": 0.012,   # 1 INR = ~0.012 USD
    "SGD": 0.76,    # 1 SGD = ~0.76 USD
    "NZD": 0.60,
    "HKD": 0.13,
    "BRL": 0.17,
    "JPY": 0.0066,
    "CHF": 1.13,
    "SEK": 0.093,
    "NOK": 0.091,
    "DKK": 0.145,
    "PLN": 0.25,
    "PHP": 0.017,
    "MYR": 0.23,
    "IDR": 0.000063,
    "PKR": 0.0036,
}

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
        "User-Agent": "HardwareStudioCommandCenter/5.2",
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


def load_freelancer_messages() -> list[dict]:
    """Load structured Freelancer messages list."""
    if os.path.exists(FREELANCER_MESSAGES_JSON):
        try:
            with open(FREELANCER_MESSAGES_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            logger.warning(f"Error reading {FREELANCER_MESSAGES_JSON}: {e}")
    return []


def save_freelancer_messages(msgs: list[dict], max_items: int = 100):
    """Save structured Freelancer messages list."""
    try:
        os.makedirs(WWW_DIR, exist_ok=True)
        capped = msgs[-max_items:]
        with open(FREELANCER_MESSAGES_JSON, "w", encoding="utf-8") as f:
            json.dump(capped, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving {FREELANCER_MESSAGES_JSON}: {e}")


def load_matched_jobs() -> list[dict]:
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


def save_matched_jobs(jobs: list[dict], max_items: int = 250):
    """Save structured matched jobs queue."""
    try:
        os.makedirs(WWW_DIR, exist_ok=True)
        capped = jobs[-max_items:]
        with open(MATCHED_JOBS_JSON, "w", encoding="utf-8") as f:
            json.dump(capped, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving {MATCHED_JOBS_JSON}: {e}")


def load_fiverr_inbox() -> list[dict]:
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


def save_fiverr_inbox(inbox: list[dict], max_items: int = 100):
    """Save structured Fiverr client inquiry inbox."""
    try:
        os.makedirs(WWW_DIR, exist_ok=True)
        capped = inbox[-max_items:]
        with open(FIVERR_INBOX_JSON, "w", encoding="utf-8") as f:
            json.dump(capped, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving {FIVERR_INBOX_JSON}: {e}")


def get_app_url() -> str:
    """Retrieve public web app URL, checking tunnel_url.txt first."""
    if os.path.exists(TUNNEL_URL_FILE):
        try:
            with open(TUNNEL_URL_FILE, "r", encoding="utf-8") as f:
                tunnel = f.read().strip()
                if tunnel.startswith("https://"):
                    return tunnel
        except Exception:
            pass
    return os.environ.get("VERCEL_APP_URL", DEFAULT_VERCEL_APP_URL)


def resolve_user_id(token: str, configured_id: str) -> int | None:
    """Resolve numeric Freelancer User ID via config or /users/0.1/self/ API."""
    if configured_id and str(configured_id).isdigit():
        return int(configured_id)

    url = f"{FREELANCER_API_BASE}/users/0.1/self/"
    try:
        resp = requests.get(url, headers=get_auth_headers(token), timeout=15)
        if resp.status_code == 200:
            user_data = resp.json().get("result", {})
            user_id = user_data.get("id")
            username = user_data.get("username")
            logger.info(f"Resolved Freelancer account: '{username}' (ID: {user_id})")
            return user_id
    except Exception as e:
        logger.error(f"Error querying Freelancer self endpoint: {e}")
    return YOUR_USER_ID


def sync_profile_skills(token: str, user_id: int):
    """
    Auto-sync core hardware skill tags with Freelancer profile on startup.
    Ensures account has PCB, KiCad, Solidworks, 3D printing etc. enabled so auto-bids don't 403.
    """
    logger.info("--- [Auto-Sync Profile Skills] ---")
    url = f"{FREELANCER_API_BASE}/users/0.1/self/jobs/"
    form_data = [("jobs[]", sid) for sid in HARDWARE_SKILL_IDS]
    encoded_data = urllib.parse.urlencode(form_data)

    headers = {
        "freelancer-oauth-v1": token,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "HardwareStudioCommandCenter/5.2",
    }
    try:
        resp = requests.post(url, data=encoded_data, headers=headers, timeout=12)
        if resp.status_code == 200:
            logger.info(f"✅ Successfully synced {len(HARDWARE_SKILL_IDS)} core hardware skills with Freelancer profile.")
        else:
            logger.warning(f"Profile skill sync returned HTTP {resp.status_code}: {resp.text[:180]}")
    except Exception as e:
        logger.warning(f"Failed to auto-sync profile skills: {e}")


# ---------------------------------------------------------------------------
# Strict 2-Layer Niche Filtering
# ---------------------------------------------------------------------------
def evaluate_project(title: str, description: str, skills: list[str]) -> tuple[bool, str | None, list[str]]:
    """
    Evaluates project against strict hardware niche rules:
    1. Rejects any project containing ANY blacklisted term in title or description.
    2. Requires at least ONE Primary Hardware Design Keyword.
    3. Captures Secondary Context Keywords as bonus tags only.
    """
    combined = f"{title}\n{description}\n{' '.join(skills)}".lower()

    # 1. Strict Blacklist Check
    matched_blacklist = []
    for bl_kw in BLACKLIST_KEYWORDS:
        bl_l = bl_kw.lower()
        if " " in bl_l or "-" in bl_l:
            if bl_l in combined:
                matched_blacklist.append(bl_kw)
        else:
            pattern = r"\b" + re.escape(bl_l) + r"\b"
            if re.search(pattern, combined):
                matched_blacklist.append(bl_kw)

    if matched_blacklist:
        return False, f"Blacklisted ({', '.join(matched_blacklist)})", matched_blacklist

    # 2. Layer 1: Primary Hardware Design Keywords (MANDATORY)
    matched_primary = []
    for kw in PRIMARY_HARDWARE_KEYWORDS:
        kw_l = kw.lower()
        if kw_l == "2-layer":
            if re.search(r"\b2[- ]layer\b", combined):
                matched_primary.append(kw)
        elif kw_l == "step":
            if re.search(r"(?:\.step\b|\bstep\s+(?:file|model|format|cad|3d|export)\b|\b(?:cad|3d|export)\s+step\b)", combined):
                matched_primary.append(kw)
        elif kw_l in ["stl", "pcb"]:
            if re.search(r"\b" + re.escape(kw_l) + r"\b", combined):
                matched_primary.append(kw)
        elif " " in kw_l or "-" in kw_l:
            if kw_l in combined:
                matched_primary.append(kw)
        else:
            pattern = r"\b" + re.escape(kw_l) + r"\b"
            if re.search(pattern, combined):
                matched_primary.append(kw)

    if not matched_primary:
        return False, "No primary hardware design keywords found (pure software/web ignored)", []

    # 3. Layer 2: Secondary Context Keywords (Bonus Context)
    matched_secondary = []
    for kw in SECONDARY_CONTEXT_KEYWORDS:
        kw_l = kw.lower()
        if re.search(r"\b" + re.escape(kw_l) + r"\b", combined):
            matched_secondary.append(kw)

    all_matched = matched_primary + [k for k in matched_secondary if k not in matched_primary]
    return True, None, all_matched


# ---------------------------------------------------------------------------
# Currency Conversion to USD ($)
# ---------------------------------------------------------------------------
def convert_to_usd(amount: float | None, currency_code: str, api_rate: float | None = None) -> float | None:
    """Convert native currency amount to USD ($)."""
    if amount is None:
        return None
    code = (currency_code or "USD").upper()
    if code == "USD":
        return round(float(amount), 2)

    # Check fallback rates table
    rate_to_usd = FALLBACK_USD_RATES.get(code)
    if rate_to_usd:
        return round(float(amount) * rate_to_usd, 2)

    # If API provides exchange_rate relative to USD
    if api_rate and api_rate > 0:
        if api_rate > 2.0:  # e.g. INR 83 per USD -> USD = amount / 83
            return round(float(amount) / api_rate, 2)
        else:  # e.g. EUR 1.08 USD per EUR -> USD = amount * 1.08
            return round(float(amount) * api_rate, 2)

    return round(float(amount), 2)


def convert_usd_to_native(usd_amount: float, currency_code: str, api_rate: float | None = None) -> float:
    """Convert USD amount back to project native currency for Freelancer bidding."""
    code = (currency_code or "USD").upper()
    if code == "USD":
        return round(float(usd_amount), 2)

    rate_to_usd = FALLBACK_USD_RATES.get(code)
    if rate_to_usd and rate_to_usd > 0:
        return round(float(usd_amount) / rate_to_usd, 2)

    if api_rate and api_rate > 0:
        if api_rate > 2.0:
            return round(float(usd_amount) * api_rate, 2)
        else:
            return round(float(usd_amount) / api_rate, 2)

    return round(float(usd_amount), 2)


def format_project_budget(project: dict) -> dict:
    """Format project budget minimum and maximum with native and USD ($) conversion."""
    budget = project.get("budget", {}) or {}
    currency = project.get("currency", {}) or {}
    sign = currency.get("sign", "$")
    code = currency.get("code", "USD")
    api_rate = currency.get("exchange_rate")

    min_b = budget.get("minimum")
    max_b = budget.get("maximum")
    min_val = float(min_b) if min_b is not None else None
    max_val = float(max_b) if max_b is not None else None

    min_usd = convert_to_usd(min_val, code, api_rate)
    max_usd = convert_to_usd(max_val, code, api_rate)

    if min_val is not None and max_val is not None:
        native_str = f"{sign}{min_val:g} - {sign}{max_val:g} {code}"
    elif min_val is not None:
        native_str = f"{sign}{min_val:g}+ {code}"
    elif max_val is not None:
        native_str = f"Up to {sign}{max_val:g} {code}"
    else:
        native_str = "Unspecified"

    if min_usd is not None and max_usd is not None:
        usd_str = f"${min_usd:g} - ${max_usd:g} USD"
    elif min_usd is not None:
        usd_str = f"${min_usd:g}+ USD"
    elif max_usd is not None:
        usd_str = f"Up to ${max_usd:g} USD"
    else:
        usd_str = "Unspecified"

    if code == "USD":
        combined_display = usd_str
    else:
        combined_display = f"{usd_str} ({native_str})"

    return {
        "min_budget": min_val,
        "max_budget": max_val,
        "currency": code,
        "currency_sign": sign,
        "exchange_rate": api_rate,
        "min_budget_usd": min_usd,
        "max_budget_usd": max_usd,
        "native_display": native_str,
        "usd_display": usd_str,
        "budget_display": combined_display,
    }


# ---------------------------------------------------------------------------
# Dynamic Multi-Paragraph Proposal Generator
# ---------------------------------------------------------------------------
def generate_proposal(job_title: str, description: str, matched_keywords: list[str]) -> str:
    """
    Generates a human-sounding 3-paragraph proposal:
    1. Greeting & Hook referencing the exact title and matched technology.
    2. Tailored Body addressing PCB, 3D Case Enclosure, or Combined requirements.
    3. Closing & Workflow explaining DRC checks, early 3D previews, and call to action.
    """
    clean_title = re.sub(r"\s+", " ", job_title).strip()
    kws_lower = [k.lower() for k in matched_keywords]

    # Categorize match focus
    pcb_triggers = ["pcb", "kicad", "schematic", "gerber", "breadboard", "fritzing", "2-layer", "carrier board", "breakout board"]
    case_triggers = ["enclosure", "3d print", "3d-printable", "stl", "step", "case design"]

    has_pcb = any(k in kws_lower for k in pcb_triggers)
    has_case = any(k in kws_lower for k in case_triggers)

    tech_mentions = [k for k in matched_keywords[:4]]
    tech_str = ", ".join(tech_mentions) if tech_mentions else "hardware design"

    # Paragraph 1: Greeting & Hook
    p1 = f"Hi! I just read through your specs for \"{clean_title}\"—specifically the {tech_str} requirements."

    # Paragraph 2: Tailored Body
    if has_pcb and has_case:
        p2 = (
            "I specialize in end-to-end hardware development, taking circuits from breadboard or schematic into a finished, "
            "cased product. For your project, I will design a clean, noise-isolated 2-layer PCB in KiCad with full schematic capture, "
            "optimized component placement, and complete DRC verification. Concurrently, I will design a custom 3D-printable enclosure "
            "(providing both production STL and parametric STEP files) modeled directly around the PCB dimensions to guarantee exact "
            "mounting hole tolerances, connector alignment, and secure snap-fit or screw-boss closures."
        )
    elif has_pcb:
        p2 = (
            "I specialize in reliable, production-ready PCB layout in KiCad. For your project, I will turn your schematic or prototype into "
            "a robust 2-layer board layout, ensuring clean ground planes, proper trace width sizing, and thorough Design Rule Checks (DRC). "
            "You will receive manufacturing-ready Gerber archives (100% verified for JLCPCB/PCBWay), drill files, pick-and-place files, and a "
            "structured Bill of Materials (BOM) with active manufacturer part numbers for effortless assembly."
        )
    elif has_case:
        p2 = (
            "I specialize in precision 3D mechanical enclosure design for electronics. For your project, I will model a clean, highly durable "
            "custom enclosure (delivering print-ready STL and editable STEP files) tailored precisely to your board dimensions, mounting points, "
            "cable reliefs, and port cutouts. I design specifically for additive manufacturing (FDM/SLA) with optimal wall thicknesses, print "
            "orientations, and tight snap-fit or threaded insert tolerances."
        )
    else:
        p2 = (
            "I have extensive hands-on experience designing modular hardware, sensor boards, and microcontroller carrier circuits. "
            "I emphasize clean schematics, signal integrity, proper decoupling, and complete manufacturing documentation so your hardware "
            "revision functions reliably on the first spin."
        )

    # Paragraph 3: Closing & Workflow
    p3 = (
        "I provide early 3D and layout previews so you can review and request adjustments before the final production files are generated, "
        "and I run full Design Rule Checks against your manufacturer rules. Could you share your wiring diagram, component list, or size "
        "constraints so I can get started?"
    )

    return f"{p1}\n\n{p2}\n\n{p3}"


# ---------------------------------------------------------------------------
# Freelancer API Bid Submission Helper
# ---------------------------------------------------------------------------
def submit_freelancer_bid(token: str, user_id: int, project_id: int, amount: float, period: int, description: str) -> tuple[bool, dict | str]:
    """Submit a bid to Freelancer.com API via POST /api/projects/0.1/bids/."""
    url = f"{FREELANCER_API_BASE}/projects/0.1/bids/"
    payload = {
        "project_id": int(project_id),
        "bidder_id": int(user_id),
        "amount": round(float(amount), 2),
        "period": int(period),
        "milestone_percentage": 100,
        "description": description,
    }
    try:
        resp = requests.post(url, json=payload, headers=get_auth_headers(token), timeout=15)
        if 200 <= resp.status_code < 300:
            return True, resp.json()
        else:
            err_msg = resp.text
            try:
                err_data = resp.json()
                err_msg = err_data.get("message") or err_data.get("error") or str(err_data)
            except Exception:
                pass
            return False, f"HTTP {resp.status_code}: {err_msg}"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Discord Notifications Helper
# ---------------------------------------------------------------------------
def send_discord_notification(webhook_url: str, title: str, description: str, fields: list = None, color: int = 0x10B981, url: str = None):
    """Send rich embed notification to Discord Webhook."""
    if not webhook_url:
        return

    embed = {
        "title": title[:256],
        "description": description[:2048],
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Hardware Studio HQ // J5 Autonomous Node"},
    }
    if url:
        embed["url"] = url
    if fields:
        embed["fields"] = fields

    payload = {
        "username": "Hardware Studio HQ",
        "embeds": [embed],
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if 200 <= resp.status_code < 300:
            logger.info(f"Discord alert posted: '{title[:60]}'")
    except Exception as e:
        logger.error(f"Failed to send Discord notification: {e}")


# ---------------------------------------------------------------------------
# Core Job Polling & 2-Tier Bidding Logic
# ---------------------------------------------------------------------------
def poll_and_scout_jobs(token: str, webhook_url: str, self_user_id: int):
    """
    Polls Freelancer active projects API, evaluates with strict 2-layer filtering,
    converts currencies to USD, generates dynamic tailored proposals, and applies
    the 2-Tier Smart Bidding strategy:
      - Tier 1: Fixed-Price $15 - $65 USD -> Automatically place bid immediately!
      - Tier 2: > $65 USD or Hourly or Error -> Route to 'needs_confirmation' queue.
    """
    logger.info("--- [Job Polling & 2-Tier Bidding Evaluation] ---")
    seen_jobs = load_id_set(SEEN_JOBS_FILE)
    matched_jobs_list = load_matched_jobs()
    existing_matched_map = {j.get("project_id"): j for j in matched_jobs_list if j.get("project_id")}

    logger.info(f"Loaded {len(seen_jobs)} seen jobs, {len(matched_jobs_list)} saved matched jobs.")

    url = f"{FREELANCER_API_BASE}/projects/0.1/projects/active/"
    params = {
        "limit": 25,
        "full_description": "true",
        "job_details": "true",
    }

    try:
        resp = requests.get(url, headers=get_auth_headers(token), params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"Error fetching active projects from Freelancer API: {e}")
        return

    projects = data.get("result", {}).get("projects", [])
    logger.info(f"Retrieved {len(projects)} active projects from Freelancer.")

    new_seen = set(seen_jobs)
    processed_count = 0
    new_auto_bids = 0
    new_confirmations = 0
    app_base_url = get_app_url()

    for project in projects:
        proj_id = project.get("id")
        if not proj_id or proj_id in seen_jobs:
            continue

        proj_status = project.get("status")
        if proj_status != "active":
            new_seen.add(proj_id)
            continue

        title = project.get("title", "")
        raw_desc = project.get("description", "") or project.get("preview_description", "")
        clean_desc = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw_desc)).strip()
        jobs_list = [j.get("name", "") for j in (project.get("jobs") or [])]
        proj_type = project.get("type", "fixed")  # 'fixed' or 'hourly'

        is_match, reason, matched_kws = evaluate_project(title, clean_desc, jobs_list)

        if is_match:
            seo_url = project.get("seo_url")
            project_url = f"https://www.freelancer.com/projects/{seo_url}" if seo_url else f"https://www.freelancer.com/projects/{proj_id}"
            budget_info = format_project_budget(project)

            # Generate Tailored 3-Paragraph Proposal
            proposal_text = generate_proposal(title, clean_desc, matched_kws)

            min_usd = budget_info["min_budget_usd"] or 0.0
            max_usd = budget_info["max_budget_usd"] or min_usd

            # Determine Tier:
            # Tier 1 Auto-Apply Criteria: Fixed-price project with budget min between $15 and $65 USD
            # (or max budget allows bidding <= $45 USD)
            is_tier_1 = (
                proj_type == "fixed" and
                ((15.0 <= min_usd <= 65.0) or (min_usd < 15.0 and max_usd >= 30.0))
            )

            job_record = {
                "project_id": proj_id,
                "title": title,
                "url": project_url,
                "description": clean_desc,
                "type": proj_type,
                "min_budget": budget_info["min_budget"],
                "max_budget": budget_info["max_budget"],
                "currency": budget_info["currency"],
                "currency_sign": budget_info["currency_sign"],
                "exchange_rate": budget_info["exchange_rate"],
                "min_budget_usd": budget_info["min_budget_usd"],
                "max_budget_usd": budget_info["max_budget_usd"],
                "native_display": budget_info["native_display"],
                "usd_display": budget_info["usd_display"],
                "budget_display": budget_info["budget_display"],
                "skills": jobs_list,
                "matched_keywords": matched_kws,
                "proposal": proposal_text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            if is_tier_1:
                # Calculate auto-bid amount in USD (between $30 and $40 USD)
                bid_usd = max(min_usd, 30.0)
                bid_usd = min(bid_usd, 40.0)
                if max_usd and max_usd < bid_usd and max_usd >= 20.0:
                    bid_usd = max_usd

                # Convert to native currency for Freelancer API submission
                native_bid = convert_usd_to_native(bid_usd, budget_info["currency"], budget_info["exchange_rate"])
                bid_period = 4

                logger.info(f"🤖 [TIER 1 AUTO-BID] Submitting bid on #{proj_id} '{title[:50]}': ${bid_usd:g} USD ({budget_info['currency_sign']}{native_bid:g} {budget_info['currency']})")
                bid_ok, bid_result = submit_freelancer_bid(
                    token=token,
                    user_id=self_user_id,
                    project_id=proj_id,
                    amount=native_bid,
                    period=bid_period,
                    description=proposal_text
                )

                if bid_ok:
                    new_auto_bids += 1
                    job_record["bid_status"] = "auto_applied"
                    job_record["applied_at"] = datetime.now(timezone.utc).isoformat()
                    job_record["bid_amount_usd"] = bid_usd
                    job_record["bid_amount_native"] = native_bid
                    job_record["bid_period"] = bid_period
                    job_record["bid_result"] = bid_result

                    # Quiet Discord Alert
                    fields = [
                        {"name": "💰 Client Budget", "value": budget_info["budget_display"], "inline": True},
                        {"name": "🎯 Auto-Bid Sent", "value": f"**${bid_usd:g} USD** ({budget_info['currency_sign']}{native_bid:g} {budget_info['currency']})", "inline": True},
                        {"name": "⏱ Period", "value": f"{bid_period} Days", "inline": True},
                        {"name": "🛠 Matched Niche", "value": f"`{', '.join(matched_kws)}`", "inline": False},
                        {"name": "🔗 Links", "value": f"[Open in Studio]({app_base_url}?view=freelancer&tab=applied) • [View on Freelancer]({project_url})", "inline": False},
                    ]
                    send_discord_notification(
                        webhook_url=webhook_url,
                        title=f"✅ [AUTO-APPLIED] {title[:80]}",
                        description=f"**Auto-bid placed:** ${bid_usd:g} USD\n\n**Proposal Preview:**\n> {proposal_text[:280]}...",
                        fields=fields,
                        color=0x10B981,  # Emerald
                        url=project_url
                    )
                else:
                    logger.warning(f"Auto-bid failed on #{proj_id}: {bid_result}")
                    # If 403 or missing skill requirement, gracefully route to needs_confirmation
                    pause_reason = "Missing Skill Tag on Profile" if ("403" in str(bid_result) or "skill" in str(bid_result).lower()) else f"Auto-Bid Error ({str(bid_result)[:50]})"
                    job_record["bid_status"] = "needs_confirmation"
                    job_record["pause_reason"] = pause_reason
                    new_confirmations += 1

                    confirm_url = f"{app_base_url}?view=freelancer&tab=confirmation&project_id={proj_id}"
                    fields = [
                        {"name": "⚠️ Pause Reason", "value": f"**{pause_reason}**", "inline": True},
                        {"name": "💰 Budget", "value": budget_info["budget_display"], "inline": True},
                        {"name": "🎯 Matched", "value": f"`{', '.join(matched_kws)}`", "inline": True},
                        {"name": "⚡ Action", "value": f"[👉 **Review & Bid in Command Center**]({confirm_url})", "inline": False},
                    ]
                    send_discord_notification(
                        webhook_url=webhook_url,
                        title=f"⚠️ [ACTION NEEDED] {title[:80]}",
                        description=f"Auto-bid paused: **{pause_reason}**.\nReview the job specs and send manual bid from the dashboard.",
                        fields=fields,
                        color=0xF59E0B,  # Amber
                        url=confirm_url
                    )

            else:
                # Tier 2: Needs Confirmation (High Budget > $65 USD or Hourly)
                new_confirmations += 1
                if proj_type == "hourly":
                    pause_reason = "Hourly Contract (Review Rate)"
                else:
                    pause_reason = f"High Value Project: ${min_usd:g} USD (Requires Custom Bid)"

                job_record["bid_status"] = "needs_confirmation"
                job_record["pause_reason"] = pause_reason

                confirm_url = f"{app_base_url}?view=freelancer&tab=confirmation&project_id={proj_id}"
                fields = [
                    {"name": "⚠️ Review Reason", "value": f"**{pause_reason}**", "inline": True},
                    {"name": "💰 Client Budget", "value": budget_info["budget_display"], "inline": True},
                    {"name": "🎯 Niche Tech", "value": f"`{', '.join(matched_kws)}`", "inline": True},
                    {"name": "⚡ Action Required", "value": f"[🚀 **Review & Approve Bid in Studio**]({confirm_url}) • [🔗 Freelancer]({project_url})", "inline": False},
                ]
                send_discord_notification(
                    webhook_url=webhook_url,
                    title=f"⚠️ [ACTION NEEDED: HIGH-VALUE LEAD] {title[:75]}",
                    description=f"**Lead Paused for Approval:** {pause_reason}\n\n**Generated Proposal Preview:**\n> {proposal_text[:280]}...",
                    fields=fields,
                    color=0xF59E0B,  # Warning Amber
                    url=confirm_url
                )

            # Save / update queue
            matched_jobs_list.append(job_record)
            existing_matched_map[proj_id] = job_record

        new_seen.add(proj_id)
        processed_count += 1

    save_id_set(SEEN_JOBS_FILE, new_seen)
    save_matched_jobs(matched_jobs_list)
    logger.info(f"Scout cycle finished: Evaluated {processed_count} projects | {new_auto_bids} Auto-Applied | {new_confirmations} Awaiting Confirmation.")


# ---------------------------------------------------------------------------
# Fiverr IMAP Email Listener (Zero-Ban Local Gmail IMAP)
# ---------------------------------------------------------------------------
def poll_fiverr_imap(webhook_url: str):
    """
    Zero-ban Fiverr IMAP Email Listener on J5.
    Connects to imap.gmail.com with standard imaplib (0 extra RAM overhead)
    and scans unread emails from @fiverr.com for client inquiries, custom offers, and briefs.
    """
    logger.info("--- [Fiverr IMAP Inbox Check] ---")
    email_user = os.environ.get("EMAIL_ADDRESS")
    email_pass = os.environ.get("EMAIL_APP_PASSWORD")
    imap_host = os.environ.get("IMAP_SERVER", "imap.gmail.com")

    inbox = load_fiverr_inbox()
    seen_fiverr_ids = load_id_set(SEEN_FIVERR_FILE)
    dismissed_fiverr_ids = load_id_set(DISMISSED_FIVERR_FILE)

    if not email_user or not email_pass:
        logger.info("Fiverr IMAP: EMAIL_ADDRESS or EMAIL_APP_PASSWORD not configured. Skipping live IMAP.")
        return

    try:
        mail = imaplib.IMAP4_SSL(imap_host, 993, timeout=15)
        mail.login(email_user, email_pass)
        mail.select("INBOX")

        status, messages = mail.search(None, '(FROM "fiverr.com")')
        if status != "OK" or not messages[0]:
            logger.info("No Fiverr emails found in inbox.")
            mail.logout()
            return

        msg_ids = messages[0].split()
        recent_ids = msg_ids[-10:]  # Last 10 Fiverr emails

        new_seen = set(seen_fiverr_ids)
        new_inquiries = 0

        for mid in reversed(recent_ids):
            mid_str = mid.decode("utf-8")
            if mid_str in seen_fiverr_ids or mid_str in dismissed_fiverr_ids:
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
                body_text = msg.get_payload(decode=True).decode("utf-8", errors="replace")

            clean_html = re.sub(r"<style.*?</style>", " ", body_text, flags=re.DOTALL | re.I)
            clean_html = re.sub(r"<script.*?</script>", " ", clean_html, flags=re.DOTALL | re.I)
            clean_html = re.sub(r"<[^>]+>", " ", clean_html)
            clean_body = re.sub(r"\s+", " ", clean_html).strip()
            if "#outlook" in clean_body or len(clean_body) < 15:
                clean_body = f"New client message from @{sender} regarding your active services."
            snippet = (clean_body[:260] + "...") if len(clean_body) > 260 else clean_body

            if sender and sender not in ["Fiverr", "Fiverr Client"]:
                fiverr_url = f"https://www.fiverr.com/inbox/{sender}"
            else:
                fiverr_link_match = re.search(r'https://[a-zA-Z0-9.-]*fiverr\.com/[^\s"\'<>]+', body_text)
                fiverr_url = fiverr_link_match.group(0) if fiverr_link_match else "https://www.fiverr.com/inbox"

            inquiry_type = "New Message"
            if "custom offer" in sub_lower:
                inquiry_type = "Custom Offer"
            elif "brief" in sub_lower:
                inquiry_type = "Buyer Brief"
            elif "order" in sub_lower:
                inquiry_type = "New Order"

            inquiry_entry = {
                "id": mid_str,
                "sender": sender,
                "subject": subject,
                "snippet": snippet,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "fiverr_link": fiverr_url,
                "status": "unread",
                "inquiry_type": inquiry_type,
            }

            inbox.insert(0, inquiry_entry)
            new_seen.add(mid_str)
            new_inquiries += 1

            logger.info(f"🟢 [FIVERR INQUIRY] from '{sender}': {subject}")

            fields = [
                {"name": "Client", "value": f"`@{sender}`", "inline": True},
                {"name": "Type", "value": inquiry_type, "inline": True},
                {"name": "Direct Link", "value": f"[Open Conversation on Fiverr]({fiverr_url})", "inline": False},
            ]
            send_discord_notification(
                webhook_url=webhook_url,
                title=f"🟢 [FIVERR] {inquiry_type}: @{sender}",
                description=f"**{subject}**\n\n{snippet}",
                fields=fields,
                color=0x10B981,  # Emerald
                url=fiverr_url,
            )

        mail.close()
        mail.logout()
        save_id_set(SEEN_FIVERR_FILE, new_seen)
        save_fiverr_inbox(inbox)
        logger.info(f"Fiverr IMAP check finished. Recorded {new_inquiries} new inquiries.")

    except Exception as e:
        logger.error(f"Error checking Fiverr IMAP: {e}")


# ---------------------------------------------------------------------------
# Freelancer Messages & Replies Listener
# ---------------------------------------------------------------------------
def poll_unread_messages(token: str, self_user_id: int, webhook_url: str):
    """Polls Freelancer threads endpoint for incoming client messages."""
    logger.info("--- [Freelancer Thread Notifications Check] ---")
    seen_msgs = load_id_set(SEEN_MSGS_FILE)

    threads_url = f"{FREELANCER_API_BASE}/messages/0.1/threads/"
    params = {"limit": 10}

    try:
        resp = requests.get(threads_url, headers=get_auth_headers(token), params=params, timeout=15)
        resp.raise_for_status()
        threads_data = resp.json()
    except Exception as e:
        logger.error(f"Error querying Freelancer threads: {e}")
        return

    threads = threads_data.get("result", {}).get("threads", [])
    if not threads:
        return

    thread_ids = [t.get("id") for t in threads if t.get("id")]
    if not thread_ids:
        return

    msg_url = f"{FREELANCER_API_BASE}/messages/0.1/messages/"
    msg_params = [("threads[]", tid) for tid in thread_ids]

    try:
        m_resp = requests.get(msg_url, headers=get_auth_headers(token), params=msg_params, timeout=15)
        m_resp.raise_for_status()
        msg_data = m_resp.json()
    except Exception as e:
        logger.error(f"Error fetching messages from threads: {e}")
        return

    messages = msg_data.get("result", {}).get("messages", [])
    new_seen_msgs = set(seen_msgs)
    new_alerts = 0
    all_stored_msgs = load_freelancer_messages()
    stored_ids = {str(m.get("id")) for m in all_stored_msgs}

    for msg in messages:
        msg_id = msg.get("id")
        if not msg_id:
            continue

        sender_id = msg.get("from_user")
        msg_text = msg.get("message", "").strip()
        thread_id = msg.get("thread_id")
        timestamp = msg.get("time_created")
        ts_iso = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat() if timestamp else datetime.now(timezone.utc).isoformat()

        # Add to structured inbox list if not present
        if str(msg_id) not in stored_ids:
            all_stored_msgs.insert(0, {
                "id": str(msg_id),
                "thread_id": str(thread_id),
                "from_user": str(sender_id),
                "message": msg_text,
                "timestamp": ts_iso,
                "is_self": bool(sender_id and self_user_id and int(sender_id) == int(self_user_id)),
                "link": f"https://www.freelancer.com/messages/thread/{thread_id}"
            })
            stored_ids.add(str(msg_id))

        if msg_id in seen_msgs:
            continue

        if sender_id and self_user_id and int(sender_id) == int(self_user_id):
            new_seen_msgs.add(msg_id)
            continue

        logger.info(f"🔔 NEW FREELANCER MESSAGE detected! ID: {msg_id} from User: {sender_id}")

        fields = [
            {"name": "Sender User ID", "value": str(sender_id), "inline": True},
            {"name": "Thread ID", "value": str(thread_id), "inline": True},
            {"name": "Direct Link", "value": f"[Open Message Thread](https://www.freelancer.com/messages/thread/{thread_id})", "inline": False},
        ]
        send_discord_notification(
            webhook_url=webhook_url,
            title="📬 New Message on Freelancer.com!",
            description=msg_text if msg_text else "*[Empty or attachment message]*",
            fields=fields,
            color=0x2563EB,  # Blue
            url=f"https://www.freelancer.com/messages/thread/{thread_id}"
        )

        new_seen_msgs.add(msg_id)
        new_alerts += 1

    save_id_set(SEEN_MSGS_FILE, new_seen_msgs)
    save_freelancer_messages(all_stored_msgs)


# ---------------------------------------------------------------------------
# Thermal & ESP32 Watchdogs
# ---------------------------------------------------------------------------
def check_battery_thermal_watchdog(webhook_url: str):
    """Monitor battery temperature and capacity on Samsung J5 (SM-J530F)."""
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
            logger.warning(f"🔥 [THERMAL WARNING] J5 Battery temp {temp_c}°C exceeds 39.0°C limit!")
            fields = [
                {"name": "Current Temperature", "value": f"**{temp_c}°C**", "inline": True},
                {"name": "Battery Level", "value": f"{capacity}%", "inline": True},
                {"name": "Watchdog Limit", "value": "39.0°C", "inline": True},
                {"name": "Device", "value": "Samsung Galaxy J5 (SM-J530F)", "inline": True},
                {"name": "Recommendation", "value": "Reduce background load or unplug charger to avoid thermal throttling.", "inline": False},
            ]
            send_discord_notification(
                webhook_url=webhook_url,
                title="🔥 [THERMAL WARNING] J5 Battery Exceeds 39.0°C!",
                description=f"Device battery temperature reached **{temp_c}°C** (Battery Level: {capacity}%). Thermal watchdog triggered.",
                fields=fields,
                color=0xEF4444,  # Red
            )


def check_esp32_pihole_watchdog(webhook_url: str):
    """Monitor ESP32-C3 Pi-hole node health via HTTP port 80."""
    ip = os.environ.get("ESP32_PIHOLE_IP", "192.168.1.250")
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
    except Exception as e:
        logger.debug(f"ESP32 check failed: {e}")

    if is_alive:
        if state.get("consecutive_failures", 0) > 0 and state.get("last_alert_sent", False) and webhook_url:
            send_discord_notification(
                webhook_url=webhook_url,
                title="✅ [ESP32 PI-HOLE RECOVERED] DNS Node Online",
                description=f"The ESP32-C3 Pi-hole DNS ad-blocker node at **{url}** is back online and responding to HTTP requests.",
                fields=[
                    {"name": "Target Node", "value": f"`{ip}:{port}`", "inline": True},
                    {"name": "Status", "value": "Operational (HTTP 200)", "inline": True},
                    {"name": "Timestamp", "value": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), "inline": True},
                ],
                color=0x10B981,  # Emerald
            )
        state["consecutive_failures"] = 0
        state["last_alert_sent"] = False
        logger.info(f"ESP32 Pi-hole Check: {url} is ONLINE (HTTP 200)")
    else:
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        fail_count = state["consecutive_failures"]
        logger.warning(f"⚠️ ESP32-C3 Pi-hole node ({url}) unreachable (failures: {fail_count})")
        if fail_count >= 2 and not state.get("last_alert_sent", False) and webhook_url:
            send_discord_notification(
                webhook_url=webhook_url,
                title="🚨 [ESP32 PI-HOLE OFFLINE] DNS Node Unreachable!",
                description=f"The ESP32-C3 Pi-hole DNS ad-blocker node at **{url}** failed {fail_count} consecutive health checks.",
                fields=[
                    {"name": "Target Node", "value": f"`{ip}:{port}`", "inline": True},
                    {"name": "Failures", "value": str(fail_count), "inline": True},
                    {"name": "Status", "value": "Offline / HTTP Unresponsive", "inline": True},
                    {"name": "Impact", "value": "Local LAN ad blocking and DNS resolution may be degraded.", "inline": False},
                ],
                color=0xEF4444,  # Red
            )
            state["last_alert_sent"] = True

    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save {state_file}: {e}")


# ---------------------------------------------------------------------------
# Dashboard Stats Writer
# ---------------------------------------------------------------------------
def write_stats_json():
    """Writes structured summary stats to www/stats.json."""
    try:
        os.makedirs(WWW_DIR, exist_ok=True)
        seen_jobs = load_id_set(SEEN_JOBS_FILE)
        matched_jobs = load_matched_jobs()
        seen_msgs = load_id_set(SEEN_MSGS_FILE)
        fiverr_inbox = load_fiverr_inbox()

        applied_jobs = [j for j in matched_jobs if j.get("bid_status") in ["auto_applied", "bid_sent"]]
        needs_confirm = [j for j in matched_jobs if j.get("bid_status") in ["needs_confirmation", "pending"]]
        dismissed_jobs = [j for j in matched_jobs if j.get("bid_status") == "dismissed"]
        fiverr_unread = [m for m in fiverr_inbox if m.get("status") == "unread"]

        # Calculate applied today count
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        applied_today = [
            j for j in applied_jobs
            if j.get("applied_at", j.get("bid_timestamp", "")).startswith(today_str)
        ]

        stats = {
            "total_processed_jobs": len(seen_jobs),
            "total_scouted_matches": len(matched_jobs),
            "applied_today_count": len(applied_today),
            "total_applied_count": len(applied_jobs),
            "needs_confirmation_count": len(needs_confirm),
            "dismissed_jobs": len(dismissed_jobs),
            "total_processed_messages": len(seen_msgs),
            "fiverr_inbox_count": len(fiverr_inbox),
            "fiverr_unread_count": len(fiverr_unread),
            "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_run_iso": datetime.now(timezone.utc).isoformat(),
            "primary_keywords": PRIMARY_HARDWARE_KEYWORDS,
            "secondary_keywords": SECONDARY_CONTEXT_KEYWORDS,
            "blacklist_keywords": BLACKLIST_KEYWORDS,
            "mode": "2-Tier Smart Auto-Bidder & Homelab OS",
            "status": "online",
            "device": "Samsung Galaxy J5 (Android 9 / Termux)",
            "app_url": get_app_url(),
        }
        with open(STATS_JSON, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
        logger.info(f"Dashboard stats written: {STATS_JSON}")

        if os.path.exists(LOG_FILE) and not os.path.exists(LOG_SYMLINK):
            try:
                os.symlink(LOG_FILE, LOG_SYMLINK)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Failed to write stats.json: {e}")


# ---------------------------------------------------------------------------
# Main Execution Cycle
# ---------------------------------------------------------------------------
def run_cycle():
    """Main execution loop run by cron or standalone."""
    start_time = time.time()
    load_env_file()

    token = os.environ.get("FREELANCER_OAUTH_TOKEN")
    discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    user_id_raw = os.environ.get("FREELANCER_USER_ID", "YOUR_USER_ID")

    # Thermal & ESP32 Watchdog Checks
    check_battery_thermal_watchdog(discord_webhook)
    check_esp32_pihole_watchdog(discord_webhook)

    if not token:
        logger.error("FREELANCER_OAUTH_TOKEN not set in environment or .env. Aborting cycle.")
        return

    logger.info("==================================================")
    logger.info("Starting 2-Tier Hardware Scout & Auto-Bid Cycle")

    user_id = resolve_user_id(token, user_id_raw)

    # 1. Auto-sync profile skills with Freelancer API
    sync_profile_skills(token, user_id)

    # 2. Poll Active Projects, evaluate 2-layer niche, auto-bid Tier 1 or queue Tier 2
    poll_and_scout_jobs(token, discord_webhook, user_id)

    # 3. Poll Freelancer Unread Messages
    poll_unread_messages(token, user_id, discord_webhook)

    # 4. Poll Fiverr IMAP Emails
    poll_fiverr_imap(discord_webhook)

    # 5. Write Stats JSON
    write_stats_json()

    elapsed = round(time.time() - start_time, 2)
    logger.info(f"Hardware cycle finished cleanly in {elapsed}s.")
    logger.info("==================================================")

    gc.collect()


def main():
    if "--loop" in sys.argv:
        poll_interval = 900  # 15 minutes
        logger.info(f"Running continuously in loop mode (every {poll_interval}s)...")
        while True:
            try:
                run_cycle()
            except Exception as e:
                logger.error(f"Unhandled error in cycle: {e}", exc_info=True)
            time.sleep(poll_interval)
    else:
        run_cycle()


if __name__ == "__main__":
    main()
