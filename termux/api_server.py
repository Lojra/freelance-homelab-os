#!/usr/bin/env python3
"""
Lightweight Pure-Python API, Telemetry & Static Server for J5 Command Center.
Provides REST endpoints on port 8080 with full CORS support:
  GET  /api/state           -> stats + pending jobs + all_scouted + fiverr_inbox + last 50 log lines + real-time telemetry & pings
  POST /api/bid             -> protected by PIN, submits bid to Freelancer API
  POST /api/dismiss         -> dismisses a job lead
  POST /api/reopen          -> re-queues a dismissed/past job lead back to pending deck
  POST /api/scan            -> triggers an immediate J5 hardware scout & inbox poll
  POST /api/profile-skills  -> syncs hardware skills with Freelancer profile
  GET  /api/fiverr          -> returns fiverr inbox
  POST /api/fiverr/read     -> marks fiverr inquiry as read
  POST /api/fiverr/delete   -> deletes a fiverr message (or 'all') and appends to dismissed_fiverr.json
  DELETE /api/fiverr        -> deletes a fiverr message (or 'all')
  GET  /*                   -> serves static dashboard files from www/
"""

import os
import sys
import json
import re
import time
import threading
import collections
import subprocess
import urllib.request
import urllib.parse
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WWW_DIR = os.path.join(BASE_DIR, "www")
STATS_FILE = os.path.join(WWW_DIR, "stats.json")
MATCHED_JOBS_FILE = os.path.join(WWW_DIR, "matched_jobs.json")
MATCHED_CONTESTS_FILE = os.path.join(WWW_DIR, "matched_contests.json")
FIVERR_INBOX_FILE = os.path.join(WWW_DIR, "fiverr_inbox.json")
DISMISSED_FIVERR_FILE = os.path.join(WWW_DIR, "dismissed_fiverr.json")
FREELANCER_MSGS_FILE = os.path.join(WWW_DIR, "freelancer_messages.json")
PROPOSAL_TEMPLATES_FILE = os.path.join(BASE_DIR, "proposal_templates.json")
LOG_FILE = os.path.join(BASE_DIR, "job_bot.log")
ENV_FILE = os.path.join(BASE_DIR, ".env")
TUNNEL_FILE = os.path.join(WWW_DIR, "tunnel_url.txt")
RUN_SCRIPT = os.path.join(BASE_DIR, "run_job_bot.sh")
HOMEWORK_STATE_FILE = os.path.join(WWW_DIR, "homework_state.json")
HOMEWORK_PDF_FILE = os.path.join(WWW_DIR, "homework_latest.pdf")

DEFAULT_PIN = "1337"
HARDWARE_SKILL_IDS = [43, 76, 111, 265, 394, 440, 612, 630, 1347, 1657]

FALLBACK_USD_RATES = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.30, "AUD": 0.65, "CAD": 0.72,
    "INR": 0.012, "SGD": 0.76, "NZD": 0.60, "HKD": 0.13, "BRL": 0.17, "JPY": 0.0066, "CHF": 1.13
}

def send_discord_alert(title, description, fields=None, color=0x10B981, url=None):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        return
    embed = {
        "title": title[:256],
        "description": description[:2048],
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Hardware Studio HQ // J5 API"}
    }
    if url:
        embed["url"] = url
    if fields:
        embed["fields"] = fields
    payload = json.dumps({"username": "Hardware Studio HQ", "embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json", "User-Agent": "J5-API/5.2"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception as e:
        print(f"[WARN] Failed to send Discord alert: {e}", file=sys.stderr)

# Rolling history buffers (last 20 points)
HISTORY_MAX = 20
cpu_history = collections.deque([25.0] * HISTORY_MAX, maxlen=HISTORY_MAX)
mem_history = collections.deque([85.0] * HISTORY_MAX, maxlen=HISTORY_MAX)

# Network state for KiB/s delta calculation
net_state = {
    "last_time": time.time(),
    "last_rx": 0,
    "last_tx": 0,
    "rx_kib_s": 0.0,
    "tx_kib_s": 0.0,
}

# Network Ping Latency State (Internet, Gateway, ESP32)
ping_state = {
    "internet": {"target": "1.1.1.1", "status": "online", "latency_ms": 18.5, "name": "Internet (Cloudflare)"},
    "gateway": {"target": "192.168.1.1", "status": "online", "latency_ms": 2.1, "name": "Gateway Router"},
    "esp32": {"target": "192.168.1.250", "status": "online", "latency_ms": 21.7, "name": "ESP32-C3 Pi-hole", "configured": True, "http_port_80": "online"},
    "mqtt_broker": {"status": "online", "port": 1883},
    "last_check": datetime.now(timezone.utc).isoformat(),
}

# ESP32 Pi-hole telemetry state
esp32_pihole_state = {
    "target": "192.168.1.250:80",
    "ip": "192.168.1.250",
    "port": 80,
    "status": "online",
    "latency_ms": 21.7,
    "http_status": 200,
    "blocking": True,
    "lookups": "2412",
    "blocked_count": "814",
    "blocked_percent": "33%",
    "domains_on_lists": "208,814",
    "devices": "6",
    "uptime": "2h 51m",
    "url": "http://192.168.1.250:80",
    "last_check": datetime.now(timezone.utc).isoformat(),
}


def load_env():
    """Load key/value pairs from .env file into os.environ."""
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
            print(f"[WARN] Error reading .env: {e}", file=sys.stderr)


load_env()


def get_token():
    return os.environ.get("FREELANCER_OAUTH_TOKEN", "YOUR_FREELANCER_OAUTH_TOKEN")


def get_user_id():
    uid = os.environ.get("FREELANCER_USER_ID", "YOUR_FREELANCER_USER_ID")
    return int(uid) if uid.isdigit() else YOUR_FREELANCER_USER_ID


def get_configured_pin():
    return os.environ.get("DASHBOARD_PIN", os.environ.get("API_AUTH_PIN", DEFAULT_PIN))


def get_last_log_lines(n=50):
    """Retrieve last n lines from job_bot.log."""
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return [line.strip() for line in lines[-n:]]
    except Exception as e:
        return [f"[LOG READ ERROR] {e}"]


def load_json_file(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def save_json_file(filepath, data):
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[ERROR] Failed writing {filepath}: {e}", file=sys.stderr)


def sample_pings():
    """Run lightweight ping checks against 1.1.1.1, Gateway, and ESP32-C3 Pi-hole."""
    global esp32_pihole_state
    gateway_ip = os.environ.get("GATEWAY_IP", "192.168.1.1")
    esp32_ip = os.environ.get("ESP32_PIHOLE_IP", os.environ.get("ESP32_IP", "192.168.1.250"))
    esp32_port = int(os.environ.get("ESP32_PIHOLE_PORT", 80))

    targets = [
        ("internet", "1.1.1.1", "Internet (Cloudflare)"),
        ("gateway", gateway_ip, "Gateway Router"),
        ("esp32", esp32_ip, "ESP32-C3 Pi-hole"),
    ]

    for key, host, label in targets:
        try:
            t0 = time.time()
            out = subprocess.check_output(
                ["ping", "-c", "1", "-W", "2", host],
                stderr=subprocess.DEVNULL,
                timeout=3
            ).decode("utf-8", errors="replace")
            m = re.search(r"time=([0-9.]+)\s*ms", out)
            lat = round(float(m.group(1)), 1) if m else round((time.time() - t0) * 1000, 1)
            ping_state[key] = {
                "target": host,
                "name": label,
                "status": "online",
                "latency_ms": lat,
                "configured": True
            }
        except Exception:
            ping_state[key] = {
                "target": host,
                "name": label,
                "status": "offline",
                "latency_ms": None,
                "configured": True
            }

    # ESP32 Pi-hole HTTP Port 80 Check & HTML Scrape
    esp_url = f"http://{esp32_ip}:{esp32_port}"
    try:
        t0 = time.time()
        req = urllib.request.Request(esp_url, headers={"User-Agent": "HomelabPiholeScout/1.0"})
        with urllib.request.urlopen(req, timeout=2.5) as r:
            http_code = r.getcode()
            body = r.read().decode("utf-8", errors="replace")
            lat_http = round((time.time() - t0) * 1000, 1)

            lookups_m = re.search(r"Lookups<b>(.*?)</b>", body)
            blocked_m = re.search(r"Blocked<b>(.*?)\s*\((.*?)\)</b>", body)
            domains_m = re.search(r"Domains on lists<b>(.*?)</b>", body)
            devices_m = re.search(r"Devices<b>(.*?)</b>", body)
            uptime_m = re.search(r"Uptime<b>(.*?)</b>", body)
            blocking_on = "Blocking is ON" in body

            esp32_pihole_state = {
                "target": f"{esp32_ip}:{esp32_port}",
                "ip": esp32_ip,
                "port": esp32_port,
                "status": "online" if http_code == 200 else "degraded",
                "latency_ms": ping_state["esp32"].get("latency_ms") or lat_http,
                "http_latency_ms": lat_http,
                "http_status": http_code,
                "blocking": blocking_on,
                "lookups": lookups_m.group(1).strip() if lookups_m else None,
                "blocked_count": blocked_m.group(1).strip() if blocked_m else None,
                "blocked_percent": blocked_m.group(2).strip() if blocked_m else None,
                "domains_on_lists": domains_m.group(1).strip() if domains_m else None,
                "devices": devices_m.group(1).strip() if devices_m else None,
                "uptime": uptime_m.group(1).strip() if uptime_m else None,
                "url": esp_url,
                "last_check": datetime.now(timezone.utc).isoformat(),
            }
            ping_state["esp32"]["status"] = "online"
            ping_state["esp32"]["http_port_80"] = "online"
    except Exception as e:
        esp32_pihole_state["status"] = "offline"
        esp32_pihole_state["http_status"] = 0
        esp32_pihole_state["last_error"] = str(e)
        esp32_pihole_state["last_check"] = datetime.now(timezone.utc).isoformat()
        ping_state["esp32"]["http_port_80"] = "offline"

    # Verify Mosquitto on port 1883
    mosq_online = False
    try:
        ps_out = subprocess.check_output(["ps", "-A"], stderr=subprocess.DEVNULL, timeout=2).decode()
        mosq_online = "mosquitto" in ps_out
    except Exception:
        mosq_online = True
    ping_state["mqtt_broker"] = {"status": "online" if mosq_online else "idle", "port": 1883}
    ping_state["last_check"] = datetime.now(timezone.utc).isoformat()


def sample_telemetry():
    """Read hardware telemetry from Linux /proc and /sys files."""
    t = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "device_model": "Samsung Galaxy J5 (SM-J530F)",
        "cpu": {
            "percent": 25.0,
            "load_1m": 1.0,
            "load_5m": 1.0,
            "load_15m": 1.0,
            "cores": 4,
            "history": list(cpu_history),
        },
        "memory": {
            "total_mb": 1816.0,
            "used_mb": 1500.0,
            "free_mb": 316.0,
            "percent": 82.5,
            "history": list(mem_history),
        },
        "storage": {
            "total_gb": 10.45,
            "used_gb": 6.82,
            "free_gb": 3.63,
            "percent": 65.3,
        },
        "network": {
            "interface": "wlan0",
            "rx_bytes": 0,
            "tx_bytes": 0,
            "rx_kib_s": net_state["rx_kib_s"],
            "tx_kib_s": net_state["tx_kib_s"],
        },
        "esp32_pihole": dict(esp32_pihole_state),
        "network_pings": dict(ping_state),
        "battery": {
            "percent": 70,
            "temp_c": 27.5,
            "status": "Charging",
        },
        "uptime": {
            "seconds": int(time.monotonic()),
            "formatted": "Up 3h 30m",
        },
        "services": [
            {"id": "cron", "name": "job-scout-cron", "status": "active", "type": "cron"},
            {"id": "imap", "name": "fiverr-imap-listener", "status": "active", "type": "worker"},
            {"id": "http", "name": "http-api-8080", "status": "active", "type": "daemon"},
            {"id": "wake", "name": "wake-lock-daemon", "status": "active", "type": "system"},
            {
                "id": "dns",
                "name": "esp32-pihole",
                "status": "active" if esp32_pihole_state.get("status") == "online" else "offline",
                "type": "dns",
                "target": f"{esp32_pihole_state.get('ip', '192.168.1.250')}:{esp32_pihole_state.get('port', 80)}",
                "url": esp32_pihole_state.get("url", "http://192.168.1.250:80"),
                "latency_ms": esp32_pihole_state.get("latency_ms"),
                "blocking": esp32_pihole_state.get("blocking", True),
            },
            {"id": "mqtt", "name": "mosquitto-1883", "status": "active", "type": "broker"},
        ],
    }

    # 1. CPU & Uptime via 'uptime' command
    try:
        raw_uptime = subprocess.check_output(["uptime"], stderr=subprocess.STDOUT, timeout=2).decode().strip()
        if "load average:" in raw_uptime:
            parts = raw_uptime.split("load average:")[1].strip().split(",")
            l1 = float(parts[0].strip())
            l5 = float(parts[1].strip())
            l15 = float(parts[2].strip())
            t["cpu"]["load_1m"] = l1
            t["cpu"]["load_5m"] = l5
            t["cpu"]["load_15m"] = l15
            cpu_pct = min(100.0, max(0.0, round((l1 / 4.0) * 100.0, 1)))
            t["cpu"]["percent"] = cpu_pct

        if "up " in raw_uptime:
            up_str = raw_uptime.split("up ")[1].split(",")[0].strip()
            t["uptime"]["formatted"] = f"Up {up_str}"
    except Exception:
        pass

    # 2. Memory via /proc/meminfo
    try:
        mem = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    k = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    mem[k] = int(val)
        tot_kb = mem.get("MemTotal", 1860040)
        avail_kb = mem.get("MemAvailable", mem.get("MemFree", 0) + mem.get("Buffers", 0) + mem.get("Cached", 0))
        used_kb = max(0, tot_kb - avail_kb)
        tot_mb = round(tot_kb / 1024, 1)
        used_mb = round(used_kb / 1024, 1)
        free_mb = round(avail_kb / 1024, 1)
        mem_pct = round((used_kb / tot_kb) * 100.0, 1) if tot_kb > 0 else 0.0

        t["memory"]["total_mb"] = tot_mb
        t["memory"]["used_mb"] = used_mb
        t["memory"]["free_mb"] = free_mb
        t["memory"]["percent"] = mem_pct
    except Exception:
        pass

    # 3. Storage via os.statvfs
    try:
        st = os.statvfs("/data/data/com.termux/files")
        tot_b = st.f_blocks * st.f_frsize
        free_b = st.f_bavail * st.f_frsize
        used_b = tot_b - free_b
        t["storage"]["total_gb"] = round(tot_b / (1024**3), 2)
        t["storage"]["used_gb"] = round(used_b / (1024**3), 2)
        t["storage"]["free_gb"] = round(free_b / (1024**3), 2)
        t["storage"]["percent"] = round((used_b / tot_b) * 100.0, 1) if tot_b > 0 else 0.0
    except Exception:
        pass

    # 4. Battery & Temp
    try:
        if os.path.exists("/sys/class/power_supply/battery/capacity"):
            with open("/sys/class/power_supply/battery/capacity", "r") as f:
                t["battery"]["percent"] = int(f.read().strip())
        if os.path.exists("/sys/class/power_supply/battery/temp"):
            with open("/sys/class/power_supply/battery/temp", "r") as f:
                t["battery"]["temp_c"] = round(int(f.read().strip()) / 10.0, 1)
        if os.path.exists("/sys/class/power_supply/battery/status"):
            with open("/sys/class/power_supply/battery/status", "r") as f:
                t["battery"]["status"] = f.read().strip()
    except Exception:
        pass

    # 5. Network wlan0 I/O
    try:
        now = time.time()
        dt = max(0.5, now - net_state["last_time"])
        rx_now = 0
        tx_now = 0
        if os.path.exists("/proc/net/dev"):
            with open("/proc/net/dev", "r") as f:
                for line in f:
                    if "wlan0:" in line:
                        cols = line.split(":")[1].split()
                        rx_now = int(cols[0])
                        tx_now = int(cols[8])
                        break
        t["network"]["rx_bytes"] = rx_now
        t["network"]["tx_bytes"] = tx_now

        if net_state["last_rx"] > 0 and rx_now >= net_state["last_rx"]:
            delta_rx = rx_now - net_state["last_rx"]
            net_state["rx_kib_s"] = round((delta_rx / dt) / 1024.0, 1)
            net_state["rx_mbps"] = round((delta_rx * 8.0) / (dt * 1_000_000.0), 2)
        else:
            net_state["rx_kib_s"] = 0.0
            net_state["rx_mbps"] = 0.0

        if net_state["last_tx"] > 0 and tx_now >= net_state["last_tx"]:
            delta_tx = tx_now - net_state["last_tx"]
            net_state["tx_kib_s"] = round((delta_tx / dt) / 1024.0, 1)
            net_state["tx_mbps"] = round((delta_tx * 8.0) / (dt * 1_000_000.0), 2)
        else:
            net_state["tx_kib_s"] = 0.0
            net_state["tx_mbps"] = 0.0

        net_state["last_time"] = now
        net_state["last_rx"] = rx_now
        net_state["last_tx"] = tx_now

        t["network"]["rx_kib_s"] = net_state["rx_kib_s"]
        t["network"]["tx_kib_s"] = net_state["tx_kib_s"]
        t["network"]["download_mbps"] = net_state["rx_mbps"]
        t["network"]["upload_mbps"] = net_state["tx_mbps"]
        t["network"]["speed_display"] = f"↓ {net_state['rx_mbps']} Mbps / ↑ {net_state['tx_mbps']} Mbps" 
    except Exception:
        pass

    # Update rolling buffers
    cpu_history.append(t["cpu"]["percent"])
    mem_history.append(t["memory"]["percent"])
    t["cpu"]["history"] = list(cpu_history)
    t["memory"]["history"] = list(mem_history)

    return t


# Telemetry Cache to throttle API and eliminate CPU spikes from rapid frontend polling
CACHED_TELEMETRY = None
LAST_TELEMETRY_TIME = 0.0
TELEMETRY_CACHE_TTL = 15.0  # Cache telemetry for at least 15 seconds

def get_cached_telemetry(force: bool = False) -> dict:
    global CACHED_TELEMETRY, LAST_TELEMETRY_TIME
    now = time.time()
    if not force and CACHED_TELEMETRY and (now - LAST_TELEMETRY_TIME < TELEMETRY_CACHE_TTL):
        return CACHED_TELEMETRY
    try:
        sample_pings()
    except Exception:
        pass
    CACHED_TELEMETRY = sample_telemetry()
    LAST_TELEMETRY_TIME = now
    return CACHED_TELEMETRY


def telemetry_background_loop():
    """Lightweight background sampler running every 20s to keep rolling history warm without CPU spikes."""
    counter = 0
    while True:
        try:
            if counter % 3 == 0:
                sample_pings()
            get_cached_telemetry(force=True)
        except Exception:
            pass
        counter += 1
        time.sleep(20)


class J5CommandHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.command} {self.path} - {args[0]}")

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Auth-Pin, Authorization")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def send_json(self, status_code, data):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def parse_body_json(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                raw = self.rfile.read(content_length).decode("utf-8")
                return json.loads(raw)
        except Exception as e:
            print(f"[WARN] Failed parsing JSON body: {e}", file=sys.stderr)
        return {}

    def is_authenticated(self, body_data=None):
        pin_header = self.headers.get("X-Auth-Pin")
        if not pin_header:
            auth_header = self.headers.get("Authorization", "")
            if auth_header.lower().startswith("bearer "):
                pin_header = auth_header[7:].strip()

        pin_query = None
        if "?" in self.path:
            try:
                params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                pin_query = params.get("pin", [None])[0] or params.get("auth_pin", [None])[0]
            except Exception:
                pass

        pin_body = None
        if body_data and isinstance(body_data, dict):
            pin_body = body_data.get("pin") or body_data.get("auth_pin")

        configured_pin = get_configured_pin()
        for candidate in [pin_header, pin_query, pin_body]:
            if candidate and str(candidate).strip() == configured_pin:
                return True
        return False

    # ----------------------------------------------------
    # GET Handlers
    # ----------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        # Protect all /api/* routes with PIN authentication
        if path.startswith("/api/"):
            if not self.is_authenticated():
                self.send_json(401, {"error": "Unauthorized: Invalid or missing X-Auth-Pin"})
                return

        if path == "/api/state":
            stats = load_json_file(STATS_FILE, {})
            all_scouted = load_json_file(MATCHED_JOBS_FILE, [])
            applied_jobs = [j for j in all_scouted if j.get("bid_status") in ["auto_applied", "bid_sent"]]
            needs_confirmation = [j for j in all_scouted if j.get("bid_status") in ["needs_confirmation", "pending"]]
            dismissed_jobs = [j for j in all_scouted if j.get("bid_status") == "dismissed"]

            matched_contests = load_json_file(MATCHED_CONTESTS_FILE, [])
            active_contests = [c for c in matched_contests if c.get("status") != "dismissed"]

            fiverr_inbox = load_json_file(FIVERR_INBOX_FILE, [])
            freelancer_msgs = load_json_file(FREELANCER_MSGS_FILE, [])
            proposal_templates = load_json_file(PROPOSAL_TEMPLATES_FILE, {})
            logs = get_last_log_lines(60)
            telemetry = get_cached_telemetry(force=False)
            homework_state = load_json_file(HOMEWORK_STATE_FILE, {
                "status": "Pending",
                "target_date": datetime.now().strftime("%Y-%m-%d"),
                "tomorrow_lessons": [],
                "tomorrow_homework": [],
                "pdf_url": "/homework_latest.pdf",
                "alerts": []
            })

            tunnel = ""
            if os.path.exists(TUNNEL_FILE):
                try:
                    with open(TUNNEL_FILE, "r", encoding="utf-8") as f:
                        tunnel = f.read().strip()
                except Exception:
                    pass

            response = {
                "status": "online",
                "device": "Samsung Galaxy J5 (Android 9 / Termux)",
                "server_time": datetime.now(timezone.utc).isoformat(),
                "tunnel_url": tunnel,
                "stats": stats,
                "jobs": needs_confirmation,
                "applied_jobs": applied_jobs,
                "needs_confirmation": needs_confirmation,
                "dismissed_jobs": dismissed_jobs,
                "all_scouted": all_scouted,
                "contests": active_contests,
                "all_contests": matched_contests,
                "fiverr_inbox": fiverr_inbox,
                "freelancer_messages": freelancer_msgs,
                "proposal_templates": proposal_templates,
                "logs": logs,
                "telemetry": telemetry,
                "esp32_pihole": dict(esp32_pihole_state),
                "network_pings": dict(ping_state),
                "homework": homework_state,
            }
            self.send_json(200, response)
            return

        if path in ["/api/homework", "/api/homework-state"]:
            hw = load_json_file(HOMEWORK_STATE_FILE, {
                "status": "Pending",
                "target_date": datetime.now().strftime("%Y-%m-%d"),
                "tomorrow_lessons": [],
                "tomorrow_homework": [],
                "pdf_url": "/homework_latest.pdf",
                "alerts": []
            })
            self.send_json(200, {"status": "success", "homework": hw})
            return

        if path in ["/api/contests", "/api/matched-contests"]:
            matched_contests = load_json_file(MATCHED_CONTESTS_FILE, [])
            active_contests = [c for c in matched_contests if c.get("status") != "dismissed"]
            self.send_json(200, {"status": "success", "contests": active_contests, "count": len(active_contests)})
            return

        if path in ["/api/templates", "/api/proposal-templates"]:
            templates = load_json_file(PROPOSAL_TEMPLATES_FILE, {})
            self.send_json(200, {"status": "success", "templates": templates})
            return

        if path in ["/api/freelancer-messages", "/api/messages"]:
            msgs = load_json_file(FREELANCER_MSGS_FILE, [])
            self.send_json(200, {"status": "success", "messages": msgs, "count": len(msgs)})
            return

        if path == "/api/jobs":
            all_scouted = load_json_file(MATCHED_JOBS_FILE, [])
            pending = [j for j in all_scouted if j.get("bid_status") == "pending"]
            self.send_json(200, {
                "status": "success",
                "jobs": pending,
                "all_scouted": all_scouted,
                "count": len(pending),
                "total_scouted": len(all_scouted),
            })
            return

        if path == "/api/fiverr":
            fiverr_inbox = load_json_file(FIVERR_INBOX_FILE, [])
            self.send_json(200, {"status": "success", "inbox": fiverr_inbox, "count": len(fiverr_inbox)})
            return

        if path == "/api/pings":
            sample_pings()
            self.send_json(200, {"status": "success", "pings": ping_state, "esp32_pihole": esp32_pihole_state})
            return

        # Static file fallback from www/
        rel_path = parsed.path.lstrip("/")
        if not rel_path or rel_path == "":
            rel_path = "index.html"

        norm_path = os.path.normpath(os.path.join(WWW_DIR, rel_path))
        if not norm_path.startswith(WWW_DIR):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"403 Forbidden")
            return

        if os.path.isfile(norm_path):
            ext = os.path.splitext(norm_path)[1].lower()
            content_types = {
                ".html": "text/html; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".txt": "text/plain; charset=utf-8",
                ".log": "text/plain; charset=utf-8",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".pdf": "application/pdf",
                ".ico": "image/x-icon",
            }
            ct = content_types.get(ext, "application/octet-stream")
            try:
                with open(norm_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_cors_headers()
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            except Exception as e:
                self.send_json(500, {"error": f"Failed to read file: {e}"})
                return

        self.send_response(404)
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(b"404 Not Found")

    # ----------------------------------------------------
    # DELETE Handlers (Fiverr Inquiry Deletion)
    # ----------------------------------------------------
    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/"):
            if not self.is_authenticated():
                self.send_json(401, {"error": "Unauthorized: Invalid or missing X-Auth-Pin"})
                return

        if path in ["/api/fiverr", "/api/fiverr/delete"]:
            inquiry_id = params.get("id", [None])[0]
            clear_all = params.get("all", ["false"])[0].lower() in ["true", "1", "all"] or (inquiry_id == "all")

            inbox = load_json_file(FIVERR_INBOX_FILE, [])
            dismissed = load_json_file(DISMISSED_FIVERR_FILE, [])
            if not isinstance(dismissed, list):
                dismissed = list(dismissed)

            if clear_all:
                for item in inbox:
                    iid = str(item.get("id"))
                    if iid and iid not in dismissed:
                        dismissed.append(iid)
                inbox = []
            elif inquiry_id:
                target_id = str(inquiry_id)
                inbox = [item for item in inbox if str(item.get("id")) != target_id]
                if target_id not in dismissed:
                    dismissed.append(target_id)

            save_json_file(FIVERR_INBOX_FILE, inbox)
            save_json_file(DISMISSED_FIVERR_FILE, dismissed)

            stats = load_json_file(STATS_FILE, {})
            stats["fiverr_inbox_count"] = len(inbox)
            stats["fiverr_unread_count"] = sum(1 for item in inbox if item.get("status") == "unread")
            save_json_file(STATS_FILE, stats)

            self.send_json(200, {
                "status": "success",
                "message": "Fiverr messages cleared" if clear_all else f"Inquiry #{inquiry_id} deleted",
                "remaining_count": len(inbox)
            })
            return

        self.send_response(404)
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(b"404 Not Found")

    # ----------------------------------------------------
    # POST Handlers
    # ----------------------------------------------------
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self.parse_body_json()

        if path.startswith("/api/"):
            if not self.is_authenticated(body):
                self.send_json(401, {"error": "Unauthorized: Invalid or missing X-Auth-Pin"})
                return

        # Route: Submit / Approve Bid to Freelancer API
        if path in ["/api/bid", "/api/jobs/approve"]:
            if not self.is_authenticated(body):
                self.send_json(401, {"error": "Unauthorized: Invalid or missing X-Auth-Pin"})
                return

            project_id = body.get("project_id")
            amount_raw = body.get("amount") or body.get("bid_amount")
            amount_usd = body.get("amount_usd") or body.get("bid_amount_usd")
            period = body.get("period") or body.get("bid_period", 4)
            description = (body.get("description") or body.get("proposal", "")).strip()

            if not project_id or (amount_raw is None and amount_usd is None) or not description:
                self.send_json(400, {"error": "Missing required fields: project_id, amount, description"})
                return

            # Lookup project details to determine currency & conversion
            jobs = load_json_file(MATCHED_JOBS_FILE, [])
            target_job = None
            for j in jobs:
                if str(j.get("project_id")) == str(project_id):
                    target_job = j
                    break

            curr_code = (target_job.get("currency") if target_job else "USD") or "USD"
            api_rate = target_job.get("exchange_rate") if target_job else None

            # Calculate native bid amount
            if amount_usd is not None and curr_code != "USD":
                rate_to_usd = FALLBACK_USD_RATES.get(curr_code.upper(), 1.0)
                if api_rate and api_rate > 0:
                    native_amount = round(float(amount_usd) * api_rate if api_rate > 2.0 else float(amount_usd) / api_rate, 2)
                else:
                    native_amount = round(float(amount_usd) / rate_to_usd, 2)
                usd_amount = float(amount_usd)
            elif amount_raw is not None:
                native_amount = float(amount_raw)
                if curr_code == "USD":
                    usd_amount = native_amount
                else:
                    rate_to_usd = FALLBACK_USD_RATES.get(curr_code.upper(), 1.0)
                    usd_amount = round(native_amount * rate_to_usd, 2)
            else:
                native_amount = float(amount_usd)
                usd_amount = float(amount_usd)

            token = get_token()
            user_id = get_user_id()

            bid_payload = {
                "project_id": int(project_id),
                "bidder_id": int(user_id),
                "amount": round(native_amount, 2),
                "period": int(period),
                "milestone_percentage": 100,
                "description": description,
            }

            freelancer_bid_url = "https://www.freelancer.com/api/projects/0.1/bids/"
            req_data = json.dumps(bid_payload).encode("utf-8")
            req = urllib.request.Request(
                freelancer_bid_url,
                data=req_data,
                headers={
                    "freelancer-oauth-v1": token,
                    "Content-Type": "application/json",
                    "User-Agent": "HardwareStudioCommandCenter/5.2",
                },
                method="POST"
            )

            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    resp_body = resp.read().decode("utf-8")
                    resp_json = json.loads(resp_body) if resp_body else {}

                    # Update matched_jobs.json
                    now_iso = datetime.now(timezone.utc).isoformat()
                    for j in jobs:
                        if str(j.get("project_id")) == str(project_id):
                            j["bid_status"] = "bid_sent"
                            j["bid_amount"] = round(native_amount, 2)
                            j["bid_amount_usd"] = round(usd_amount, 2)
                            j["bid_period"] = int(period)
                            j["bid_timestamp"] = now_iso
                            j["applied_at"] = now_iso
                            j["proposal"] = description
                            j["bid_result"] = resp_json
                    save_json_file(MATCHED_JOBS_FILE, jobs)

                    # Update stats
                    stats = load_json_file(STATS_FILE, {})
                    stats["bids_sent"] = stats.get("bids_sent", 0) + 1
                    stats["needs_confirmation_count"] = max(0, sum(1 for j in jobs if j.get("bid_status") in ["needs_confirmation", "pending"]))
                    save_json_file(STATS_FILE, stats)

                    # Discord notification
                    proj_title = target_job.get("title", f"Project #{project_id}") if target_job else f"Project #{project_id}"
                    proj_url = target_job.get("url") if target_job else f"https://www.freelancer.com/projects/{project_id}"
                    send_discord_alert(
                        title=f"🚀 [BID APPROVED & PLACED] {proj_title[:80]}",
                        description=f"**Approved via Command Center:** ${usd_amount:g} USD ({native_amount:g} {curr_code}) in {period} days.\n\n**Proposal:**\n> {description[:280]}...",
                        fields=[
                            {"name": "Bid Amount", "value": f"${usd_amount:g} USD ({native_amount:g} {curr_code})", "inline": True},
                            {"name": "Delivery Period", "value": f"{period} Days", "inline": True},
                            {"name": "Direct Link", "value": f"[Open on Freelancer]({proj_url})", "inline": False},
                        ],
                        color=0x10B981,
                        url=proj_url
                    )

                    self.send_json(200, {
                        "status": "success",
                        "message": f"Bid placed successfully on Project #{project_id}",
                        "bid_amount": native_amount,
                        "bid_amount_usd": usd_amount,
                        "currency": curr_code,
                        "result": resp_json,
                    })
                    return

            except urllib.error.HTTPError as e:
                err_text = e.read().decode("utf-8", errors="replace")
                print(f"[ERROR] Freelancer API rejected bid: HTTP {e.code} - {err_text}", file=sys.stderr)
                try:
                    err_json = json.loads(err_text)
                except Exception:
                    err_json = {"error": err_text}
                self.send_json(e.code, {
                    "error": "Freelancer API rejected bid",
                    "code": e.code,
                    "details": err_json,
                })
                return
            except Exception as e:
                print(f"[ERROR] Bid submission failed: {e}", file=sys.stderr)
                self.send_json(500, {"error": f"Internal error sending bid: {e}"})
                return

        # Route: Save Custom Proposal Templates
        if path in ["/api/templates", "/api/templates/save", "/api/proposal-templates"]:
            if not self.is_authenticated(body):
                self.send_json(401, {"error": "Unauthorized: Invalid or missing X-Auth-Pin"})
                return

            templates = load_json_file(PROPOSAL_TEMPLATES_FILE, {})
            for key in ["greeting", "pcb_body", "case_body", "both_body", "closing"]:
                if key in body:
                    templates[key] = str(body[key]).strip()
            save_json_file(PROPOSAL_TEMPLATES_FILE, templates)
            self.send_json(200, {
                "status": "success",
                "message": "Proposal templates updated successfully",
                "templates": templates
            })
            return

        # Route: Dismiss Job Lead or Contest
        if path in ["/api/dismiss", "/api/contests/dismiss"]:
            if not self.is_authenticated(body):
                self.send_json(401, {"error": "Unauthorized: Invalid or missing X-Auth-Pin"})
                return

            contest_id = body.get("contest_id") or (body.get("id") if "contest" in path else None)
            project_id = body.get("project_id") or body.get("id")

            if contest_id:
                contests = load_json_file(MATCHED_CONTESTS_FILE, [])
                updated = False
                for c in contests:
                    if str(c.get("contest_id")) == str(contest_id):
                        c["status"] = "dismissed"
                        c["dismissed_timestamp"] = datetime.now(timezone.utc).isoformat()
                        updated = True
                save_json_file(MATCHED_CONTESTS_FILE, contests)
                self.send_json(200, {
                    "status": "success",
                    "message": f"Contest #{contest_id} dismissed",
                    "updated": updated
                })
                return

            if not project_id:
                self.send_json(400, {"error": "Missing project_id or contest_id"})
                return

            jobs = load_json_file(MATCHED_JOBS_FILE, [])
            updated = False
            for j in jobs:
                if str(j.get("project_id")) == str(project_id):
                    j["bid_status"] = "dismissed"
                    j["dismissed_timestamp"] = datetime.now(timezone.utc).isoformat()
                    updated = True
            save_json_file(MATCHED_JOBS_FILE, jobs)

            stats = load_json_file(STATS_FILE, {})
            stats["dismissed_jobs"] = stats.get("dismissed_jobs", 0) + 1
            stats["needs_confirmation_count"] = max(0, sum(1 for j in jobs if j.get("bid_status") in ["needs_confirmation", "pending"]))
            save_json_file(STATS_FILE, stats)

            self.send_json(200, {
                "status": "success",
                "message": f"Project #{project_id} dismissed",
                "updated": updated
            })
            return

        # Route: Re-open Dismissed Job Lead
        if path == "/api/reopen":
            if not self.is_authenticated(body):
                self.send_json(401, {"error": "Unauthorized: Invalid or missing X-Auth-Pin"})
                return

            project_id = body.get("project_id")
            if not project_id:
                self.send_json(400, {"error": "Missing project_id"})
                return

            jobs = load_json_file(MATCHED_JOBS_FILE, [])
            updated = False
            for j in jobs:
                if j.get("project_id") == int(project_id):
                    j["bid_status"] = "pending"
                    j.pop("dismissed_timestamp", None)
                    updated = True
            save_json_file(MATCHED_JOBS_FILE, jobs)

            stats = load_json_file(STATS_FILE, {})
            stats["pending_matches"] = sum(1 for j in jobs if j.get("bid_status") == "pending")
            stats["dismissed_jobs"] = sum(1 for j in jobs if j.get("bid_status") == "dismissed")
            save_json_file(STATS_FILE, stats)

            self.send_json(200, {
                "status": "success",
                "message": f"Project #{project_id} restored to pending queue",
                "updated": updated
            })
            return

        # Route: Force J5 Scout Scan Now
        if path == "/api/scan":
            if not self.is_authenticated(body):
                self.send_json(401, {"error": "Unauthorized: Invalid or missing X-Auth-Pin"})
                return

            try:
                bash_bin = "/data/data/com.termux/files/usr/bin/bash"
                if os.path.exists(bash_bin) and os.path.exists(RUN_SCRIPT):
                    subprocess.Popen([bash_bin, RUN_SCRIPT], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    python_bin = sys.executable or "/data/data/com.termux/files/usr/bin/python"
                    bot_script = os.path.join(BASE_DIR, "job_bot.py")
                    subprocess.Popen([python_bin, bot_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                self.send_json(200, {
                    "status": "success",
                    "message": "J5 Hardware Scout & Fiverr poll initiated in background",
                    "triggered_at": datetime.now(timezone.utc).isoformat()
                })
                return
            except Exception as e:
                self.send_json(500, {"error": f"Failed to initiate scan: {e}"})
                return

        # Route: Force Homework Bot Run Now
        if path in ["/api/homework/run", "/api/homework-run"]:
            if not self.is_authenticated(body):
                self.send_json(401, {"error": "Unauthorized: Invalid or missing X-Auth-Pin"})
                return
            try:
                python_bin = sys.executable or "/data/data/com.termux/files/usr/bin/python"
                hw_script = os.path.join(BASE_DIR, "homework_bot.py")
                subprocess.Popen([python_bin, hw_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.send_json(200, {
                    "status": "success",
                    "message": "Autonomous Homework Bot triggered in background",
                    "triggered_at": datetime.now(timezone.utc).isoformat()
                })
                return
            except Exception as ex:
                self.send_json(500, {"error": f"Failed to trigger homework bot: {ex}"})
                return

        # Route: Mark Fiverr Message Read
        if path == "/api/fiverr/read":
            inquiry_id = body.get("id")
            inbox = load_json_file(FIVERR_INBOX_FILE, [])
            for item in inbox:
                if not inquiry_id or item.get("id") == str(inquiry_id):
                    item["status"] = "read"
            save_json_file(FIVERR_INBOX_FILE, inbox)

            stats = load_json_file(STATS_FILE, {})
            stats["fiverr_unread_count"] = sum(1 for item in inbox if item.get("status") == "unread")
            save_json_file(STATS_FILE, stats)

            self.send_json(200, {"status": "success", "message": "Marked as read"})
            return

        # Route: Delete or Clear Fiverr Message(s)
        if path in ["/api/fiverr/delete", "/api/fiverr/clear"]:
            inquiry_id = body.get("id")
            clear_all = body.get("all", False) or body.get("clear_all", False) or (inquiry_id == "all")

            inbox = load_json_file(FIVERR_INBOX_FILE, [])
            dismissed = load_json_file(DISMISSED_FIVERR_FILE, [])
            if not isinstance(dismissed, list):
                dismissed = list(dismissed)

            if clear_all:
                for item in inbox:
                    iid = str(item.get("id"))
                    if iid and iid not in dismissed:
                        dismissed.append(iid)
                inbox = []
            elif inquiry_id:
                target_id = str(inquiry_id)
                inbox = [item for item in inbox if str(item.get("id")) != target_id]
                if target_id not in dismissed:
                    dismissed.append(target_id)

            save_json_file(FIVERR_INBOX_FILE, inbox)
            save_json_file(DISMISSED_FIVERR_FILE, dismissed)

            stats = load_json_file(STATS_FILE, {})
            stats["fiverr_inbox_count"] = len(inbox)
            stats["fiverr_unread_count"] = sum(1 for item in inbox if item.get("status") == "unread")
            save_json_file(STATS_FILE, stats)

            self.send_json(200, {
                "status": "success",
                "message": "Fiverr messages cleared" if clear_all else f"Inquiry #{inquiry_id} deleted",
                "remaining_count": len(inbox)
            })
            return

        # Route: Sync Profile Hardware Skills
        if path == "/api/profile-skills":
            if not self.is_authenticated(body):
                self.send_json(401, {"error": "Unauthorized: Invalid or missing X-Auth-Pin"})
                return

            token = get_token()
            skills_url = "https://www.freelancer.com/api/users/0.1/self/jobs/"
            form_payload = urllib.parse.urlencode([("jobs[]", sid) for sid in HARDWARE_SKILL_IDS]).encode("utf-8")

            req = urllib.request.Request(
                skills_url,
                data=form_payload,
                headers={
                    "freelancer-oauth-v1": token,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "HardwareStudioCommandCenter/5.0",
                },
                method="PUT"
            )

            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    resp_body = resp.read().decode("utf-8")
                    resp_json = json.loads(resp_body) if resp_body else {}
                    self.send_json(200, {
                        "status": "success",
                        "message": "Hardware skills synced with Freelancer profile",
                        "skills_count": len(HARDWARE_SKILL_IDS),
                        "result": resp_json
                    })
                    return
            except urllib.error.HTTPError as e:
                err_text = e.read().decode("utf-8", errors="replace")
                self.send_json(e.code, {"error": "Failed to sync skills", "details": err_text})
                return
            except Exception as e:
                self.send_json(500, {"error": f"Error updating skills: {e}"})
                return

        self.send_response(404)
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(b"404 Not Found")


def run_server(port=8080):
    sample_telemetry()
    sample_pings()

    t = threading.Thread(target=telemetry_background_loop, daemon=True)
    t.start()

    server_address = ("0.0.0.0", port)
    httpd = HTTPServer(server_address, J5CommandHandler)
    pin = get_configured_pin()
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] J5 Proxmox/Homelab Node API listening on 0.0.0.0:{port}...")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [AUTH] Configured Dashboard PIN: {pin} (Strictly enforced on all /api/* routes)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping J5 API server...")
        httpd.server_close()


if __name__ == "__main__":
    port = 8080
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    run_server(port)
