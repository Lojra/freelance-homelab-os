# ⚡ Homelab OS // Hardware Freelance Command Center

> Transform any old Android phone into a 24/7 autonomous Homelab node, high-speed Freelancer & Fiverr scout, and interactive Swipe-to-Bid PWA with local ESP32 Pi-hole integration.

[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg)](LICENSE)
[![Platform: Android Termux](https://img.shields.io/badge/Platform-Android%20%2F%20Termux-green.svg)](https://termux.dev)
[![PWA Ready](https://img.shields.io/badge/PWA-Installable%20(iOS%20%26%20Android)-blue.svg)](#installable-pwa)
[![ESP32 Pi-hole](https://img.shields.io/badge/IoT-ESP32--C3%20Pi--hole-cyan.svg)](#esp32-pi-hole-integration)

---

## 🏛️ System Architecture

```mermaid
graph TD
    subgraph "Local LAN Homelab"
        Phone["📱 Android Device (Termux)<br/>• Python API Server (:8080)<br/>• Autonomous Job Scout Daemon<br/>• Zero-Ban Fiverr IMAP Worker<br/>• Battery Thermal Watchdog"]
        ESP32["🔌 ESP32-C3 Pi-hole Node (:80)<br/>• DNS Ad Blocking<br/>• Live Domain & Query Metrics"]
        Gateway["🌐 Home Gateway Router (:1)"]
        Phone -->|"HTTP Scrape & Ping"| ESP32
        Phone -->|"ICMP Latency"| Gateway
    end

    subgraph "Secure Edge & Tunneling"
        CF["☁️ Cloudflare Tunnel<br/>(trycloudflare.com / Zero-Trust)"]
        Phone -->|"Zero-Open-Ports Tunnel"| CF
    end

    subgraph "Web Application"
        Vercel["▲ Vercel Edge Serverless<br/>• High-Availability Dual Gateway<br/>• PIN Enforced Proxy"]
        PWA["💻 Mobile & Desktop PWA<br/>• 3D Swipe Deck (Tinder-style)<br/>• Homelab Bento Telemetry<br/>• 4-Digit PIN Security Lock"]
        CF --> Vercel
        Vercel --> PWA
    end

    subgraph "External Integrations"
        FL["⚡ Freelancer.com REST API"]
        Discord["📢 Discord Webhook Alerts"]
        Gmail["📫 Gmail IMAP (Fiverr Inquiries)"]
        Phone --> FL
        Phone --> Discord
        Phone --> Gmail
    end
```

---

## 🌟 Key Features

1. **Repurpose Old Android Phones as 24/7 Homelab Nodes**
   - Runs lightweight pure-Python HTTP API and cron daemons inside Termux with minimal RAM footprint (< 35 MB).
   - Zero root required! Includes an ADB debloater script (`optimize_phone.sh`) that sets animation scales to 0 and disables heavy OEM background services.
   - Screen stays completely off while `termux-wake-lock` keeps the CPU active.

2. **24/7 Autonomous Hardware Scout (KiCad, PCB, 3D Case Design)**
   - High-speed polling against the official Freelancer.com REST API.
   - Strict keyword matching for hardware niches: `kicad`, `pcb`, `schematic`, `gerber`, `breadboard`, `fritzing`, `enclosure`, `3d print`, `stl`, `step`, `esp32`, `arduino`, `2-layer`, `bom`.
   - Comprehensive blacklist rejection: drops projects containing `trading`, `crypto`, `forex`, `4-layer`, `rf design`, `mains voltage`, etc.
   - Never auto-bids without your explicit approval — stages matches into a pending queue.

3. **Zero-Ban Fiverr IMAP Listener**
   - Connects directly to `imap.gmail.com` using App Passwords.
   - Filters client inquiries from `@fiverr.com` and formats them into an actionable Live Inbox with one-click dismiss and reply links.

4. **Battery Thermal & ESP32 Watchdog Daemons**
   - **Battery Thermal Watchdog**: Reads `/sys/class/power_supply/battery/temp`. If battery temp exceeds **39.0°C**, fires an immediate `[THERMAL WARNING]` alert to your Discord Webhook.
   - **ESP32 Pi-hole Watchdog**: Checks HTTP port 80 of your ESP32 DNS ad-blocker every cycle. If unreachable for 2 consecutive checks, fires a Discord offline alert.

5. **Proxmox / Homelab Bento Dashboard & Swipe-to-Bid Deck**
   - **Homelab Aesthetic**: Deep obsidian matte background (`#0B0D10`), subtle emerald ambient glow, circular SVG radial gauges, and real-time SVG sparklines.
   - **Tinder-Style Swipe Deck**: Swipe Right (→) to configure and submit bids; Swipe Left (←) to dismiss.
   - **Strict 4-Digit PIN Lock**: Proxmox-style PIN lock overlay enforced on both frontend and backend (`X-Auth-Pin` header).

6. **Installable PWA (Android & iOS)**
   - Fully compliant Web App Manifest (`manifest.json`) and Service Worker (`sw.js`).
   - Thumb-friendly bottom navigation bar and 2x2 responsive sparkline grid on mobile screens.

---

## 🚀 Quick Start Guide

### Step 1: Set Up Your Android Phone (Termux)

1. Install **Termux** from [F-Droid](https://f-droid.org/packages/com.termux/).
2. Open Termux on your phone and run the one-command setup wizard:
   ```bash
   curl -sL https://raw.githubusercontent.com/Lojra/freelance-homelab-os/main/termux/setup_termux.sh | bash
   ```
3. The wizard will install Python, Cloudflared, configure your `.env`, and start the background scout cron.
4. Launch your Node API server and Cloudflare tunnel:
   ```bash
   bash ~/start_api_server.sh
   ```

### Step 2: (Optional) Optimize Phone via ADB

Connect your phone to your PC via USB and enable USB Debugging, then run:
```bash
bash termux/optimize_phone.sh
```
This disables background bloatware and turns off window animations so 100% of available RAM goes to Termux.

### Step 3: Deploy Frontend & Edge API to Vercel

1. Fork or clone this repository:
   ```bash
   git clone https://github.com/Lojra/freelance-homelab-os.git
   cd freelance-homelab-os
   ```
2. Deploy to Vercel:
   ```bash
   npm install -g vercel
   vercel --prod
   ```
3. Set your environment variables in Vercel Project Settings:
   - `DASHBOARD_PIN`: 4-digit PIN (default `1337`)
   - `J5_TUNNEL_URL`: Your `trycloudflare.com` tunnel URL
   - `FREELANCER_OAUTH_TOKEN`: Your Freelancer OAuth token
   - `FREELANCER_USER_ID`: Your Freelancer numeric user ID
   - `DISCORD_WEBHOOK_URL`: Your Discord Webhook URL
   - `ESP32_PIHOLE_IP`: Local IP of your ESP32 Pi-hole node (e.g. `192.168.1.50`)

---

## 🔒 Security & Privacy Architecture

- **Zero Cloud Storage**: All scouted job queues, Fiverr client inquiries, and logs remain strictly on your local Android device and client `sessionStorage`.
- **PIN Protected Endpoints**: All API routes (`GET /api/state`, `POST /api/bid`, `DELETE /api/fiverr`) strictly require an `X-Auth-Pin` header matching your configured `DASHBOARD_PIN`.
- **Zero Open Ports**: Uses outgoing Cloudflare Tunnels (or Tailscale) to communicate with Vercel without requiring port forwarding or exposing home IP addresses.

---

## 📄 License

Distributed under the [MIT License](LICENSE). Contributions, feature requests, and homelab setups welcome!
