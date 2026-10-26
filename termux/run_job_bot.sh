#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# Homelab OS Hardware Scout Cron Runner
# ==============================================================================

export PATH="/data/data/com.termux/files/usr/bin:$PATH"
export PYTHONUNBUFFERED=1

HOME_DIR="/data/data/com.termux/files/home"
PYTHON_BIN="/data/data/com.termux/files/usr/bin/python"
SCRIPT="$HOME_DIR/job_bot.py"
LOCKFILE="/data/data/com.termux/files/usr/tmp/job_bot.lock"

# Acquire lock to prevent overlapping runs
exec 200>"$LOCKFILE"
flock -n 200 || {
    echo "[!] Another instance of job_bot is already running. Skipping."
    exit 0
}

cd "$HOME_DIR" || exit 1
"$PYTHON_BIN" "$SCRIPT" >> "$HOME_DIR/job_bot.log" 2>&1
