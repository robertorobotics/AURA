#!/bin/bash
# Setup CAN interface for Damiao motor control
# Run with: sudo bash scripts/setup_can.sh [channel] [bitrate] [txqueuelen]
#
# Configures the CAN bus interface (can0) for the Innomaker USB2CAN-X2
# adapter (gs_usb driver) with proper TX queue length to prevent buffer
# overflow when controlling 7 motors at 60Hz.

set -e

CHANNEL="${1:-can0}"
BITRATE="${2:-1000000}"
TXQUEUELEN="${3:-256}"

echo "[CAN Setup] Configuring $CHANNEL (bitrate=$BITRATE, txqueuelen=$TXQUEUELEN)"

# Bring down if already up
ip link set "$CHANNEL" down 2>/dev/null || true

# Configure CAN type and bitrate
ip link set "$CHANNEL" type can bitrate "$BITRATE"

# Set TX queue length (critical for gs_usb adapters)
ip link set "$CHANNEL" txqueuelen "$TXQUEUELEN"

# Bring up
ip link set "$CHANNEL" up

# Verify
ACTUAL_QLEN=$(cat "/sys/class/net/$CHANNEL/tx_queue_len" 2>/dev/null || echo "?")
STATE=$(cat "/sys/class/net/$CHANNEL/operstate" 2>/dev/null || echo "?")

echo "[CAN Setup] $CHANNEL is $STATE, txqueuelen=$ACTUAL_QLEN"

if [ "$ACTUAL_QLEN" -ge "$TXQUEUELEN" ] 2>/dev/null; then
    echo "[CAN Setup] OK"
else
    echo "[CAN Setup] WARNING: txqueuelen=$ACTUAL_QLEN (expected >=$TXQUEUELEN)"
    exit 1
fi
