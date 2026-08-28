#!/bin/bash
# deploy_api.sh
# Syncs /root/api from source VPS (187.127.165.77) to all target VPS instances
# Creates/recreates tmux session named "api" on each target

SOURCE_HOST="187.127.165.77"
SOURCE_USER="root"
SOURCE_PASS="Sunny@989924"
SOURCE_PATH="/root/api"

declare -A TARGETS
TARGETS["147.93.29.45"]="Sunny@989924"
TARGETS["72.61.171.99"]="Sunny@989924"
TARGETS["77.37.47.109"]="Iceyyyyyynoob048@"
TARGETS["72.62.195.112"]="Iceyyyyyynoob048@"
TARGETS["187.77.119.92"]="Sunny@989924"
TARGETS["152.239.114.106"]="Sunny@989924"

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=15 -o ServerAliveInterval=10"

# Check sshpass
if ! command -v sshpass &>/dev/null; then
    echo "[ERROR] sshpass not installed. Run: apt-get install -y sshpass"
    exit 1
fi

echo "=== Starting deployment from ${SOURCE_HOST} ==="
echo ""

for TARGET_HOST in "${!TARGETS[@]}"; do
    TARGET_PASS="${TARGETS[$TARGET_HOST]}"

    echo "--- Deploying to ${TARGET_HOST} ---"

    # Pipe tar from source directly to target (no temp files)
    sshpass -p "$SOURCE_PASS" ssh $SSH_OPTS root@${SOURCE_HOST} \
        "tar --exclude='api/venv' -czf - -C /root api" | \
    sshpass -p "$TARGET_PASS" ssh $SSH_OPTS root@${TARGET_HOST} \
        "tar xzf - -C /root --overwrite"

    if [ $? -ne 0 ]; then
        echo "[FAILED] File sync to ${TARGET_HOST}"
        echo ""
        continue
    fi
    echo "[OK] Files synced to ${TARGET_HOST}"

    # Kill existing tmux session "api" and any orphaned api.py processes, then start fresh
    sshpass -p "$TARGET_PASS" ssh $SSH_OPTS root@${TARGET_HOST} bash << EOF
pkill -9 -f 'api.py' || true
tmux has-session -t api 2>/dev/null && tmux kill-session -t api && echo "[OK] Killed old tmux session"
tmux new-session -d -s api -c /root/api "venv/bin/python api.py"
echo "[OK] tmux session 'api' started"
EOF

    if [ $? -eq 0 ]; then
        echo "[OK] tmux session 'api' live on ${TARGET_HOST}"
    else
        echo "[FAILED] tmux setup on ${TARGET_HOST}"
    fi

    echo ""
done

echo "=== Deployment complete ==="
echo ""
echo "Verify sessions with:"
echo "  sshpass -p 'Sunny@989924' ssh root@<host> 'tmux ls'"