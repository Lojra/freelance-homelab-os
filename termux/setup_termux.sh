#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# Homelab OS: One-Click Android / Termux Setup Wizard
# Run this inside Termux on your old Android phone:
#   curl -sL https://raw.githubusercontent.com/Lojra/freelance-homelab-os/main/termux/setup_termux.sh | bash
# ==============================================================================

set -e

echo "=========================================================="
echo "    HOMELAB OS: ANDROID NODE SETUP WIZARD"
echo "    Turn any old Android phone into a 24/7 Homelab Node"
echo "=========================================================="
echo ""

# 1. Acquire Termux wake lock so Android never puts CPU to sleep
echo "[*] Step 1: Acquiring Termux Wake Lock..."
termux-wake-lock
echo "[+] Wake lock acquired. CPU will stay active with screen off."

# 2. Package updates & installation
echo "[*] Step 2: Updating package repositories and installing core packages..."
pkg update -y
pkg install -y python git cronie termux-api curl jq clang libjpeg-turbo

# 3. Python packages
echo "[*] Step 3: Installing Python dependencies..."
pip install --upgrade pip requests

# 4. Install Cloudflared for secure HTTPS tunneling without open ports
echo "[*] Step 4: Installing Cloudflare Tunnel (cloudflared)..."
ARCH=$(uname -m)
case "$ARCH" in
    aarch64) CF_ARCH="arm64" ;;
    armv7l|armv8l) CF_ARCH="arm" ;;
    x86_64) CF_ARCH="amd64" ;;
    *) CF_ARCH="arm" ;;
esac

CLOUDFLARED_BIN="/data/data/com.termux/files/usr/bin/cloudflared"
if [ ! -f "$CLOUDFLARED_BIN" ]; then
    echo "[*] Downloading cloudflared for $CF_ARCH..."
    curl -L "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$CF_ARCH" -o "$CLOUDFLARED_BIN"
    chmod +x "$CLOUDFLARED_BIN"
    echo "[+] Cloudflared installed to $CLOUDFLARED_BIN"
else
    echo "[+] Cloudflared is already installed."
fi

# 5. Environment configuration (.env)
HOME_DIR="/data/data/com.termux/files/home"
cd "$HOME_DIR"

if [ ! -f "$HOME_DIR/.env" ]; then
    echo ""
    echo "=========================================================="
    echo " CONFIGURING YOUR CREDENTIALS"
    echo "=========================================================="
    read -p "Enter Freelancer.com OAuth Token (optional): " FL_TOKEN
    read -p "Enter Freelancer.com Numeric User ID (optional): " FL_UID
    read -p "Enter Discord Webhook URL (optional): " DC_HOOK
    read -p "Enter 4-Digit Dashboard Security PIN [default: 1337]: " DB_PIN
    DB_PIN=${DB_PIN:-1337}
    read -p "Enter ESP32 Pi-hole IP on your LAN [default: 192.168.1.50]: " ESP_IP
    ESP_IP=${ESP_IP:-192.168.1.50}

    cat <<EOF > "$HOME_DIR/.env"
FREELANCER_OAUTH_TOKEN=${FL_TOKEN}
FREELANCER_USER_ID=${FL_UID}
DISCORD_WEBHOOK_URL=${DC_HOOK}
DASHBOARD_PIN=${DB_PIN}
API_AUTH_PIN=${DB_PIN}
ESP32_PIHOLE_IP=${ESP_IP}
ESP32_PIHOLE_PORT=80
EOF
    echo "[+] Configuration saved to $HOME_DIR/.env"
else
    echo "[+] Existing .env detected at $HOME_DIR/.env"
fi

# 6. Setup crontab
echo "[*] Step 5: Setting up 15-minute background scout cron..."
crond || true
(crontab -l 2>/dev/null | grep -v "run_job_bot.sh"; echo "*/15 * * * * bash $HOME_DIR/run_job_bot.sh") | crontab -
echo "[+] Crontab configured."

# 7. Make scripts executable
chmod +x "$HOME_DIR"/*.sh "$HOME_DIR"/*.py 2>/dev/null || true

echo ""
echo "=========================================================="
echo " [SUCCESS] SETUP COMPLETE!"
echo " To start your node API server and Cloudflare tunnel, run:"
echo "   bash ~/start_api_server.sh"
echo "=========================================================="
