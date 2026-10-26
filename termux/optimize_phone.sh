#!/usr/bin/env bash
# ==============================================================================
# Universal Android Homelab Optimizer & Debloater (Run via ADB on PC)
# Disables OEM background bloatware via 'pm disable-user --user 0'
# Zero rooting required! Safe to run on unrooted Samsung, Xiaomi, Motorola, etc.
# ==============================================================================

echo "=========================================================="
echo " HOMELAB OS: ANDROID NODE OPTIMIZER & DEBLOATER"
echo "=========================================================="

# Check ADB connection
if ! command -v adb >/dev/null 2>&1; then
    echo "[ERROR] adb command not found on your system."
    exit 1
fi

DEVICE_COUNT=$(adb devices | grep -v "List" | grep "device" | wc -l)
if [ "$DEVICE_COUNT" -eq 0 ]; then
    echo "[ERROR] No Android device connected via ADB. Run 'adb devices' to check."
    exit 1
fi

echo "[*] Connected device detected. Applying optimizations..."

# 1. Disable Animations for maximum CPU responsiveness
echo "[*] Setting window, transition and animator duration scales to 0..."
adb shell "settings put global window_animation_scale 0"
adb shell "settings put global transition_animation_scale 0"
adb shell "settings put global animator_duration_scale 0"

# 2. Configure screen & power saving
echo "[*] Disabling stay_on_while_plugged_in so screen stays OFF while charging..."
adb shell "settings put global stay_on_while_plugged_in 0"

# 3. Disable common background bloatware apps (Safe list)
BLOAT_PACKAGES=(
    "com.sec.android.app.sbrowser"
    "com.samsung.android.bixby.agent"
    "com.samsung.android.bixby.service"
    "com.samsung.android.app.spage"
    "com.sec.android.app.samsungapps"
    "com.google.android.youtube"
    "com.sec.android.daemonapp"
    "com.samsung.android.email.provider"
    "com.google.android.apps.maps"
    "com.android.chrome"
    "com.google.android.apps.photos"
    "com.google.android.videos"
    "com.google.android.music"
)

echo "[*] Debloating OEM background apps to free maximum RAM for Termux..."
for pkg in "${BLOAT_PACKAGES[@]}"; do
    adb shell "pm disable-user --user 0 $pkg" 2>/dev/null && echo "  [-] Disabled $pkg" || true
done

echo "=========================================================="
echo " [SUCCESS] Android Node Optimized!"
echo "   - Animations set to 0x"
echo "   - Screen timeout enabled while on charger"
echo "   - Unnecessary background apps disabled"
echo "=========================================================="
