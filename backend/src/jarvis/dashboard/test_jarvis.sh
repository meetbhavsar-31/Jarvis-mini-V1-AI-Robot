#!/bin/bash
# ===========================================================================
# JARVIS Mini V1 - Test Script
# Run this after starting your server (python app.py) to check every fixed
# feature via curl. Doesn't touch anything destructive by default.
# ===========================================================================

SERVER="http://127.0.0.1:8000"
TOKEN="$1"

PASS=0
FAIL=0

check() {
    local name="$1"; shift
    local expected="$1"; shift
    local code
    local body
    body=$(curl -s -o /tmp/jarvis_test_body -w "%{http_code}" "$@")
    code="$body"
    if [ "$code" == "$expected" ]; then
        echo "[PASS] $name  (HTTP $code)"
        PASS=$((PASS+1))
    else
        echo "[FAIL] $name  (expected HTTP $expected, got $code)"
        echo "        body: $(head -c 200 /tmp/jarvis_test_body)"
        FAIL=$((FAIL+1))
    fi
}

auth_header=()
if [ -n "$TOKEN" ]; then
    auth_header=(-H "X-API-Token: $TOKEN")
fi

echo "=================================================================="
echo " JARVIS Mini V1 - Automated Test Pass"
echo " Server: $SERVER"
if [ -n "$TOKEN" ]; then echo " Auth:   token provided"; else echo " Auth:   NONE"; fi
echo "=================================================================="

echo ""
echo "--- 1. Dashboard pages load ---"
check "Dashboard page"        200 "$SERVER/"
check "Camera page"           200 "$SERVER/Camera"
check "Controls page"         200 "$SERVER/Controls"
check "System page"           200 "$SERVER/System"

echo ""
echo "--- 2. Status & telemetry ---"
check "Robot status"          200 "$SERVER/api/robot-status"
check "Sensor data"           200 "$SERVER/api/sensor-data"
check "System stats"          200 "$SERVER/api/system-stats"
check "Activity log"          200 "$SERVER/api/activity-log"

echo ""
echo "--- 3. Auth gate on protected endpoints ---"
if [ -n "$TOKEN" ]; then
    check "move w/o token rejected"    401 "$SERVER/api/move?dir=stop&duration=0"
    check "move w/ token allowed"      200 "${auth_header[@]}" "$SERVER/api/move?dir=stop&duration=0"
else
    check "move (no auth configured)"  200 "$SERVER/api/move?dir=stop&duration=0"
fi

echo ""
echo "--- 4. Movement + emergency stop ---"
check "Move forward briefly"  200 "${auth_header[@]}" "$SERVER/api/move?dir=forward&duration=0.5"
sleep 1
check "Explicit STOP"         200 "${auth_header[@]}" "$SERVER/api/move?dir=stop&duration=0"
check "Control: stop command" 200 "${auth_header[@]}" -X POST -H "Content-Type: application/json" -d '{"command":"stop"}' "$SERVER/api/control"

echo ""
echo "--- 5. Chat: movement/question misfire regression check ---"
check "Chat: tell me weather right now" 200 -X POST -H "Content-Type: application/json" \
    -d '{"message":"tell me the weather right now","language":"en"}' "$SERVER/api/chat"
sleep 1
check "Chat: what do you see right now" 200 -X POST -H "Content-Type: application/json" \
    -d '{"message":"what do you see right now","language":"en"}' "$SERVER/api/chat"
sleep 1
check "Chat: turn left"                 200 -X POST -H "Content-Type: application/json" \
    -d '{"message":"turn left","language":"en"}' "$SERVER/api/chat"

echo ""
echo "--- 6. Snapshot capture + cloud gallery ---"
check "Trigger screenshot via control" 200 "${auth_header[@]}" -X POST -H "Content-Type: application/json" \
    -d '{"command":"screenshot"}' "$SERVER/api/control"
sleep 6
check "Fetch snapshots list"  200 "$SERVER/api/snapshots"

echo ""
echo "--- 7. Video recording ---"
check "Start recording"       200 "${auth_header[@]}" -X POST -H "Content-Type: application/json" \
    -d '{"command":"record_start"}' "$SERVER/api/control"
sleep 3
check "Stop recording"        200 "${auth_header[@]}" -X POST -H "Content-Type: application/json" \
    -d '{"command":"record_stop"}' "$SERVER/api/control"
sleep 1
check "Fetch recordings list" 200 "$SERVER/api/recordings"

echo ""
echo "--- 8. Memory endpoints ---"
check "Get all memories"      200 "$SERVER/api/memory"
check "Add memory w/ auth"    200 "${auth_header[@]}" -X POST -H "Content-Type: application/json" \
    -d '{"text":"Automated test memory entry - safe to delete."}' "$SERVER/api/memory"

echo ""
echo "--- 9. Diagnostics ---"
check "AI health"             200 "$SERVER/api/ai-health"
check "Vision health"         200 "$SERVER/api/vision-health"

echo ""
echo "--- 10. Misc controls ---"
check "Set eye color"         200 -X POST -H "Content-Type: application/json" \
    -d '{"hex_color":"#00FFCC"}' "$SERVER/api/eyes"
check "Set volume"            200 -X POST -H "Content-Type: application/json" \
    -d '{"volume_percent":60}' "$SERVER/api/volume"
check "Set language"          200 -X POST -H "Content-Type: application/json" \
    -d '{"language":"en"}' "$SERVER/api/language"
check "Cast full team to robot" 200 "$SERVER/api/cast-team"

echo ""
echo "=================================================================="
echo " RESULTS: $PASS passed, $FAIL failed"
echo "=================================================================="
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi