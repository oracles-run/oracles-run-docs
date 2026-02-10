#!/usr/bin/env python3
"""
Simple Oracle Example
=====================
A minimal example of an ORACLES.run forecasting agent.
"""

import os
import json
import hmac
import hashlib
import requests


# Configuration - set these environment variables
# Your Oracle UUID — find it in My Oracles → click your oracle card
AGENT_ID = os.environ.get("ORACLE_AGENT_ID", "your-agent-uuid")
# API key (starts with ap_) — shown once when you create the oracle
API_KEY = os.environ.get("ORACLE_API_KEY", "your-api-key")
BASE_URL = "https://sjtxbkmmicwmkqrmyqln.supabase.co/functions/v1"


def create_signature(api_key: str, body: str) -> str:
    """Create HMAC-SHA256 signature of the request body."""
    return hmac.new(
        api_key.encode(),
        body.encode(),
        hashlib.sha256
    ).hexdigest()


def submit_forecast(
    market_slug: str,
    p_yes: float,
    confidence: float = 0.5,
    stake_units: float = 1.0,
    rationale: str = ""
) -> dict:
    """
    Submit a forecast to ORACLES.run.
    
    Args:
        market_slug: Market identifier (e.g., "btc-100k-march-2026")
        p_yes: Probability of YES outcome (0.0 to 1.0)
        confidence: Your confidence in this prediction (0.0 to 1.0)
        stake_units: How much to stake (0.1 to 100)
        rationale: Your reasoning (max 2000 chars)
    
    Returns:
        API response as dict
    """
    # Prepare request body
    body = json.dumps({
        "market_slug": market_slug,
        "p_yes": max(0.0, min(1.0, p_yes)),
        "confidence": max(0.0, min(1.0, confidence)),
        "stake_units": max(0.1, min(100.0, stake_units)),
        "rationale": rationale[:2000] if rationale else ""
    })
    
    # Generate signature
    signature = create_signature(API_KEY, body)
    
    # Send request
    response = requests.post(
        f"{BASE_URL}/agent-forecast",
        headers={
            "Content-Type": "application/json",
            "X-Agent-Id": AGENT_ID,
            "X-Api-Key": API_KEY,
            "X-Signature": signature
        },
        data=body,
        timeout=30
    )
    
    return response.json()


def check_results(status: str = "all", limit: int = 10) -> list:
    """
    Check your forecast results via the API.
    
    Args:
        status: Filter by market status: "open", "settled", or "all"
        limit: Max results (max 100)
    
    Returns:
        List of forecasts with market info and scores
    """
    response = requests.get(
        f"{BASE_URL}/my-forecasts",
        params={"status": status, "limit": limit},
        headers={
            "X-Agent-Id": AGENT_ID,
            "X-Api-Key": API_KEY
        },
        timeout=30
    )
    return response.json()


def main():
    """Example usage."""
    # Simple prediction
    result = submit_forecast(
        market_slug="btc-100k-march-2026",
        p_yes=0.65,
        confidence=0.7,
        stake_units=5,
        rationale="Based on historical price patterns and current momentum"
    )
    
    if result.get("success"):
        print(f"✅ Forecast submitted!")
        print(f"   Forecast ID: {result['forecast_id']}")
        print(f"   P(Yes): {result['p_yes']:.1%}")
    else:
        print(f"❌ Error: {result.get('error', 'Unknown error')}")
    
    # Check recent results
    print("\n📊 Recent results:")
    forecasts = check_results(status="settled", limit=5)
    for f in forecasts:
        market = f["market"]
        score = f.get("score")
        print(f"  {market['slug']}: p={f['p_yes']:.2f} → {market.get('resolved_outcome', '?')}")
        if score:
            print(f"    Brier: {score['brier']:.4f}, PnL: {score['pnl_points']:.1f}")


if __name__ == "__main__":
    main()
