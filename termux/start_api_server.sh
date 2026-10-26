#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# Homelab OS Interactive API Server & Cloudflared Tunnel Launcher
# ==============================================================================

export PATH="/data/data/com.termux/files/usr/bin:$PATH"
export PYTHONUNBUFFERED=1

HOME_DIR="/data/data/com.termux/files/home"
WWW_DIR="$HOME_DIR/www"
PYTHON_BIN="/data/data/com.termux/files/usr/bin/python"
CLOUDFLARED_BIN="/data/data/com.termux/files/usr/bin/cloudflared"
PORT=8080

echo "[*] Initializing Homelab Command Center Node..."
mkdir -p "$WWW_DIR"
cd "$HOME_DIR" || exit 1

# 0. Check and launch Mosquitto MQTT broker on port 1883 if installed
if command -v mosquitto >/dev/null 2>&1; then
    if ! pgrep -x "mosquitto" > /dev/null; then
        echo "[*] Launching Mosquitto MQTT broker on port 1883..."
        nohup mosquitto > "$HOME_DIR/mosquitto.log" 2>&1 &
    fi
fi

# 1. Kill old servers
echo "[*] Stopping previous API and tunnel processes..."
pkill -f "api_server.py" 2>/dev/null
pkill -f "cloudflared tunnel" 2>/dev/null
sleep 1

# 2. Launch api_server.py in background
echo "[*] Starting Node API Server on port $PORT..."
nohup "$PYTHON_BIN" "$HOME_DIR/api_server.py" "$PORT" > "$HOME_DIR/api_server.log" 2>&1 &
API_PID=$!
echo "[+] API Server started with PID: $API_PID"

# 3. Launch cloudflared tunnel
if command -v "$CLOUDFLARED_BIN" >/dev/null 2>&1; then
    echo "[*] Launching Cloudflare Tunnel for port $PORT..."
    rm -f "$HOME_DIR/cloudflared.log"
    nohup "$CLOUDFLARED_BIN" tunnel --url "http://127.0.0.1:$PORT" > "$HOME_DIR/cloudflared.log" 2>&1 &
    TUNNEL_PID=$!
    echo "[+] Cloudflared started with PID: $TUNNEL_PID"

    # 4. Extract public trycloudflare.com URL
    echo "[*] Waiting for Cloudflare Tunnel URL..."
    TUNNEL_URL=""
    for i in {1..15}; do
        sleep 1
        if [ -f "$HOME_DIR/cloudflared.log" ]; then
            TUNNEL_URL=$(grep -o "https://[a-zA-Z0-9.-]*\.trycloudflare\.com" "$HOME_DIR/cloudflared.log" | head -n 1)
            if [ -n "$TUNNEL_URL" ]; then
                break
            fi
        fi
    done

    if [ -n "$TUNNEL_URL" ]; then
        echo "$TUNNEL_URL" > "$WWW_DIR/tunnel_url.txt"
        echo "=========================================================="
        echo " [SUCCESS] Cloudflare Public Tunnel Active:"
        echo "   $TUNNEL_URL"
        echo "=========================================================="
    else
        echo "[!] Tunnel URL not detected yet. Check $HOME_DIR/cloudflared.log"
    fi
else
    echo "[!] cloudflared not found in PATH. Running on LAN only."
fi

echo "=========================================================="
echo " HOMELAB COMMAND CENTER READY:"
echo "   Local LAN:  http://0.0.0.0:${PORT}"
echo "   API State:  http://0.0.0.0:${PORT}/api/state"
echo "=========================================================="
