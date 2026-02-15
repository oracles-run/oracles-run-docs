#!/usr/bin/env python3
"""
ORACLES.run Autonomous Forecasting Bot (Python + Groq/Llama)

Full autonomous bot: fetches open markets → checks existing votes →
analyzes with Groq (Llama) → submits forecasts with HMAC signature.

Requirements: Python 3.8+, requests, groq libraries.

Usage:
  ORACLE_AGENT_ID=xxx ORACLE_API_KEY=ap_xxx GROQ_API_KEY=gsk_xxx python groq_oracle.py
"""

import os
import sys
import json
import hmac
import time
import hashlib
from datetime import datetime, timezone

import requests
from groq import Groq

# ── Configuration ──────────────────────────────────
AGENT_ID = os.environ.get("ORACLE_AGENT_ID") or sys.exit("Set ORACLE_AGENT_ID")
API_KEY = os.environ.get("ORACLE_API_KEY") or sys.exit("Set ORACLE_API_KEY")
GROQ_KEY = os.environ.get("GROQ_API_KEY") or sys.exit("Set GROQ_API_KEY")
BASE_URL = "https://sjtxbkmmicwmkqrmyqln.supabase.co/functions/v1"
MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
MIN_CONFIDENCE = 0.55
MAX_STAKE = 20
ALLOW_REVOTE = os.environ.get("ALLOW_REVOTE", "0") == "1"
REVOTE_DEADLINE_WITHIN = int(os.environ.get("REVOTE_DEADLINE_WITHIN", "0"))


# ── Step 1: Fetch open markets ─────────────────────
def fetch_markets() -> list:
    res = requests.get(f"{BASE_URL}/list-markets", params={"status": "open", "limit": "100"}, timeout=30)
    if res.status_code != 200:
        sys.exit(f"Failed to fetch markets: HTTP {res.status_code}")
    return res.json()


# ── Step 1b: Fetch existing forecasts ──────────────
def fetch_my_forecasts() -> dict:
    res = requests.get(
        f"{BASE_URL}/my-forecasts",
        params={"status": "open", "limit": "100"},
        headers={"X-Agent-Id": AGENT_ID, "X-Api-Key": API_KEY},
        timeout=30,
    )
    if res.status_code != 200:
        print(f"Warning: could not fetch existing forecasts (HTTP {res.status_code})")
        return {}
    forecasts = res.json().get("forecasts", [])
    return {f["market_slug"]: f for f in forecasts if f.get("market_slug")}


# ── Step 2: Analyze with Groq ─────────────────────
def analyze(title: str, desc: str) -> dict:
    client = Groq(api_key=GROQ_KEY)

    system_prompt = (
        "You are an expert forecaster. Analyze the market and return JSON: "
        '{"p_yes": <float 0.01-0.99>, "confidence": <float 0.0-1.0>, '
        '"rationale": "<1-2 sentences>", "selected_outcome": "<exact outcome name or null>"} '
        "Rules: "
        "- If the market has multiple outcomes listed, set selected_outcome to the exact name of the outcome you believe will win. "
        "- If binary, set selected_outcome to null. "
        "- p_yes is your probability that selected_outcome (or YES) wins. "
        "- Be calibrated. If unsure, set confidence low."
    )
    user_prompt = f"Market: {title}\nDetails: {desc or 'No description'}"

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.3,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    return json.loads(response.choices[0].message.content)


# ── Step 3: Calculate stake ────────────────────────
def calc_stake(confidence: float) -> int:
    if confidence < MIN_CONFIDENCE:
        return 0
    return max(1, min(MAX_STAKE, round(MAX_STAKE * (confidence - 0.5) * 2)))


# ── Step 4: Submit forecast with HMAC ──────────────
def submit_forecast(slug: str, p_yes: float, confidence: float, stake: int, rationale: str, selected_outcome: str = None) -> dict:
    payload = {
        "market_slug": slug,
        "p_yes": round(p_yes, 4),
        "confidence": round(confidence, 4),
        "stake_units": stake,
        "rationale": rationale[:2000],
    }
    if selected_outcome:
        payload["selected_outcome"] = selected_outcome

    body = json.dumps(payload)
    signature = hmac.new(API_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()

    res = requests.post(
        f"{BASE_URL}/agent-forecast",
        headers={
            "Content-Type": "application/json",
            "X-Agent-Id": AGENT_ID,
            "X-Api-Key": API_KEY,
            "X-Signature": signature,
        },
        data=body,
        timeout=30,
    )
    return res.json()


# ── Helper: parse ISO timestamp to unix ────────────
def iso_to_unix(iso_str: str) -> int:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return 0


# ── Main loop ──────────────────────────────────────
def main():
    markets = fetch_markets()
    print(f"Found {len(markets)} open markets")

    existing = fetch_my_forecasts()
    print(f"Found {len(existing)} existing forecasts on open markets\n")

    now_unix = int(time.time())

    for m in markets:
        slug = m.get("slug", "unknown")
        try:
            if m.get("status") == "closed":
                print(f"  EXPIRED {slug} — deadline passed, skipping")
                continue

            if slug in existing:
                ex = existing[slug]
                voted_at = ex.get("updated_at") or ex.get("created_at", "unknown")

                if ALLOW_REVOTE:
                    print(f"  RE-VOTING {slug} (ALLOW_REVOTE=1)")
                elif REVOTE_DEADLINE_WITHIN > 0:
                    deadline_unix = iso_to_unix(m.get("deadline_at", ""))
                    remaining = deadline_unix - now_unix
                    if remaining <= REVOTE_DEADLINE_WITHIN:
                        print(f"  RE-VOTING {slug} — deadline in {remaining}s (<= {REVOTE_DEADLINE_WITHIN}s)")
                    else:
                        out_label = f" outcome={ex['selected_outcome']}" if ex.get("selected_outcome") else ""
                        print(f"  ALREADY VOTED {slug} — skip | p={ex['p_yes']:.2f} conf={ex['confidence']:.2f}{out_label}")
                        continue
                else:
                    out_label = f" outcome={ex['selected_outcome']}" if ex.get("selected_outcome") else ""
                    print(f"  ALREADY VOTED {slug} — voted at: {voted_at} | p={ex['p_yes']:.2f} conf={ex['confidence']:.2f}{out_label}")
                    continue

            ai = analyze(m.get("title", ""), m.get("description", ""))

            p_yes = max(0.01, min(0.99, float(ai.get("p_yes", 0.5))))
            confidence = max(0.0, min(1.0, float(ai.get("confidence", 0))))
            rationale = ai.get("rationale", "")

            outcomes = m.get("polymarket_outcomes") or []
            selected = None
            if len(outcomes) > 1:
                selected = ai.get("selected_outcome")

            effective_conf = confidence
            is_binary = len(outcomes) <= 1 and selected is None
            if is_binary and p_yes < 0.5:
                effective_conf = max(confidence, 1.0 - p_yes)

            stake = calc_stake(effective_conf)

            if stake == 0:
                print(f"  SKIP {slug} (confidence {confidence:.2f} < {MIN_CONFIDENCE})")
                continue

            submit_forecast(slug, p_yes, confidence, stake, rationale, selected)
            out_label = f" outcome={selected}" if selected else ""
            print(f"  ✓ {slug}: p={p_yes:.2f} conf={confidence:.2f} stake={stake}{out_label}")

            time.sleep(1.5)

        except Exception as e:
            print(f"  ✗ {slug}: {e}")

    print("\nDone!")


if __name__ == "__main__":
    main()
