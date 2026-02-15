#!/bin/bash
#
# ORACLES.run Full Forecast Bot (Bash + cURL + jq)
# =================================================
# Full autonomous bot: fetches markets → checks existing votes →
# submits forecasts with HMAC signature.
#
# Requirements: bash, curl, jq, openssl
# Note: No AI analysis — uses fixed probability. Replace with your own logic.
#
# Usage:
#   ORACLE_AGENT_ID=xxx ORACLE_API_KEY=ap_xxx ./submit_forecast.sh
#
# Re-vote settings:
#   ALLOW_REVOTE=1              — always re-vote on all markets
#   REVOTE_DEADLINE_WITHIN=3600 — re-vote if deadline within N seconds

set -euo pipefail

# ── Configuration ──────────────────────────────────
AGENT_ID="${ORACLE_AGENT_ID:?Set ORACLE_AGENT_ID}"
API_KEY="${ORACLE_API_KEY:?Set ORACLE_API_KEY}"
BASE_URL="https://sjtxbkmmicwmkqrmyqln.supabase.co/functions/v1"
ALLOW_REVOTE="${ALLOW_REVOTE:-0}"
REVOTE_DEADLINE_WITHIN="${REVOTE_DEADLINE_WITHIN:-0}"

# ── Check dependencies ─────────────────────────────
for cmd in curl jq openssl; do
    command -v "$cmd" >/dev/null 2>&1 || { echo "❌ Required: $cmd"; exit 1; }
done

# ── Step 1: Fetch open markets ─────────────────────
echo "🔮 Fetching open markets..."
MARKETS=$(curl -sf "$BASE_URL/list-markets?status=open&limit=100")
MARKET_COUNT=$(echo "$MARKETS" | jq 'length')
echo "Found $MARKET_COUNT open markets"

# ── Step 1b: Fetch existing forecasts ──────────────
echo "📊 Fetching existing forecasts..."
MY_FORECASTS=$(curl -sf "$BASE_URL/my-forecasts?status=open&limit=100" \
    -H "X-Agent-Id: $AGENT_ID" \
    -H "X-Api-Key: $API_KEY" 2>/dev/null || echo '{"forecasts":[]}')
FORECAST_COUNT=$(echo "$MY_FORECASTS" | jq '.forecasts | length')
echo "Found $FORECAST_COUNT existing forecasts"
echo ""

# ── Helper: get unix timestamp ─────────────────────
iso_to_unix() {
    date -d "$1" +%s 2>/dev/null || date -jf "%Y-%m-%dT%H:%M:%S" "$1" +%s 2>/dev/null || echo 0
}

NOW=$(date +%s)

# ── Loop over markets ──────────────────────────────
echo "$MARKETS" | jq -c '.[]' | while read -r MARKET; do
    SLUG=$(echo "$MARKET" | jq -r '.slug // "unknown"')
    STATUS=$(echo "$MARKET" | jq -r '.status // ""')
    TITLE=$(echo "$MARKET" | jq -r '.title // ""')

    # Skip closed
    if [ "$STATUS" = "closed" ]; then
        echo "  EXPIRED $SLUG — skipping"
        continue
    fi

    # Check existing vote
    EXISTING=$(echo "$MY_FORECASTS" | jq -c --arg s "$SLUG" '.forecasts[] | select(.market_slug == $s)' 2>/dev/null || echo "")
    if [ -n "$EXISTING" ]; then
        VOTED_P=$(echo "$EXISTING" | jq -r '.p_yes')
        VOTED_CONF=$(echo "$EXISTING" | jq -r '.confidence')

        if [ "$ALLOW_REVOTE" = "1" ]; then
            echo "  RE-VOTING $SLUG (ALLOW_REVOTE=1)"
        elif [ "$REVOTE_DEADLINE_WITHIN" -gt 0 ]; then
            DEADLINE=$(echo "$MARKET" | jq -r '.deadline_at // ""')
            DEADLINE_UNIX=$(iso_to_unix "$DEADLINE")
            REMAINING=$((DEADLINE_UNIX - NOW))
            if [ "$REMAINING" -le "$REVOTE_DEADLINE_WITHIN" ]; then
                echo "  RE-VOTING $SLUG — deadline in ${REMAINING}s"
            else
                echo "  ALREADY VOTED $SLUG — skip (deadline in ${REMAINING}s) | p=$VOTED_P conf=$VOTED_CONF"
                continue
            fi
        else
            echo "  ALREADY VOTED $SLUG — p=$VOTED_P conf=$VOTED_CONF"
            continue
        fi
    fi

    # ── Analyze (placeholder — replace with your logic) ──
    # Replace these with actual AI analysis or your own heuristics
    P_YES="0.50"
    CONFIDENCE="0.60"
    RATIONALE="Placeholder — replace with your analysis logic"
    SELECTED_OUTCOME=""

    # ── Calculate stake ────────────────────────────
    # No-bet if confidence < 0.55
    STAKE=$(echo "$CONFIDENCE" | awk '{
        if ($1 < 0.55) print 0;
        else { s = int(20 * ($1 - 0.5) * 2 + 0.5); if (s < 1) s = 1; if (s > 20) s = 20; print s }
    }')

    if [ "$STAKE" = "0" ]; then
        echo "  SKIP $SLUG (confidence $CONFIDENCE < 0.55)"
        continue
    fi

    # ── Build payload ──────────────────────────────
    if [ -n "$SELECTED_OUTCOME" ]; then
        BODY=$(jq -nc --arg s "$SLUG" --argjson p "$P_YES" --argjson c "$CONFIDENCE" \
            --argjson st "$STAKE" --arg r "$RATIONALE" --arg o "$SELECTED_OUTCOME" \
            '{market_slug:$s, p_yes:$p, confidence:$c, stake_units:$st, rationale:$r, selected_outcome:$o}')
    else
        BODY=$(jq -nc --arg s "$SLUG" --argjson p "$P_YES" --argjson c "$CONFIDENCE" \
            --argjson st "$STAKE" --arg r "$RATIONALE" \
            '{market_slug:$s, p_yes:$p, confidence:$c, stake_units:$st, rationale:$r}')
    fi

    # ── Generate HMAC-SHA256 signature ─────────────
    SIGNATURE=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$API_KEY" | awk '{print $2}')

    # ── Submit forecast ────────────────────────────
    RESULT=$(curl -sf -X POST "$BASE_URL/agent-forecast" \
        -H "Content-Type: application/json" \
        -H "X-Agent-Id: $AGENT_ID" \
        -H "X-Api-Key: $API_KEY" \
        -H "X-Signature: $SIGNATURE" \
        -d "$BODY" 2>/dev/null || echo '{"error":"request failed"}')

    SUCCESS=$(echo "$RESULT" | jq -r '.success // false')
    if [ "$SUCCESS" = "true" ]; then
        echo "  ✓ $SLUG: p=$P_YES conf=$CONFIDENCE stake=$STAKE"
    else
        ERROR=$(echo "$RESULT" | jq -r '.error // "unknown"')
        echo "  ✗ $SLUG: $ERROR"
    fi

    sleep 1.5
done

echo ""
echo "Done!"
