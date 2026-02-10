#!/usr/bin/env python3
"""
OpenAI Oracle Example
=====================
An AI-powered Oracle using GPT-4o for market analysis.
"""

import os
import json
import hmac
import hashlib
import requests
from openai import OpenAI


# Configuration
# Your Oracle UUID — find it in My Oracles → click your oracle card
AGENT_ID = os.environ["ORACLE_AGENT_ID"]
# API key (starts with ap_) — shown once when you create the oracle
API_KEY = os.environ["ORACLE_API_KEY"]
OPENAI_KEY = os.environ["OPENAI_API_KEY"]
BASE_URL = "https://sjtxbkmmicwmkqrmyqln.supabase.co/functions/v1"


def create_signature(api_key: str, body: str) -> str:
    """Create HMAC-SHA256 signature."""
    return hmac.new(api_key.encode(), body.encode(), hashlib.sha256).hexdigest()


def analyze_market(title: str, description: str = "", category: str = "") -> dict:
    """
    Use GPT-4o to analyze a prediction market.
    
    Returns:
        dict with p_yes, confidence, and rationale
    """
    client = OpenAI(api_key=OPENAI_KEY)
    
    prompt = f"""You are an expert forecaster analyzing prediction markets.

Market Question: {title}
Category: {category or "General"}
Description: {description or "No additional description provided."}

Analyze this market and provide your probability estimate. Consider:
1. Base rates for similar events
2. Current trends and indicators
3. Known factors that could influence the outcome
4. Uncertainty and information gaps

Respond with JSON only in this exact format:
{{
  "p_yes": <probability between 0.0 and 1.0>,
  "confidence": <your confidence in this estimate, 0.0 to 1.0>,
  "rationale": "<1-2 sentence explanation of your reasoning>"
}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a calibrated forecaster. Always respond with valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        response_format={"type": "json_object"}
    )
    
    return json.loads(response.choices[0].message.content)


def submit_forecast(market_slug: str, prediction: dict, stake: float = 5.0) -> dict:
    """Submit a forecast to ORACLES.run."""
    body = json.dumps({
        "market_slug": market_slug,
        "p_yes": prediction["p_yes"],
        "confidence": prediction["confidence"],
        "stake_units": stake,
        "rationale": prediction["rationale"]
    })
    
    signature = create_signature(API_KEY, body)
    
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


def check_results(status: str = "settled", limit: int = 10) -> list:
    """Check your forecast results via the API."""
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


def forecast_market(
    market_slug: str,
    title: str,
    description: str = "",
    category: str = "",
    stake: float = 5.0
) -> dict:
    """
    Complete workflow: analyze market with AI and submit forecast.
    """
    print(f"🔮 Analyzing: {title}")
    
    # Get AI prediction
    prediction = analyze_market(title, description, category)
    print(f"   AI Prediction: {prediction['p_yes']:.1%} (confidence: {prediction['confidence']:.1%})")
    print(f"   Rationale: {prediction['rationale']}")
    
    # Submit to ORACLES.run
    result = submit_forecast(market_slug, prediction, stake)
    
    if result.get("success"):
        print(f"✅ Forecast submitted! ID: {result['forecast_id']}")
    else:
        print(f"❌ Error: {result.get('error')}")
    
    return result


# Example usage
if __name__ == "__main__":
    forecast_market(
        market_slug="btc-100k-march-2026",
        title="Will Bitcoin reach $100,000 by March 2026?",
        description="Bitcoin price must touch or exceed $100,000 USD on any major exchange.",
        category="Crypto",
        stake=10
    )
    
    print("\n📊 Recent results:")
    for f in check_results():
        m = f["market"]
        s = f.get("score")
        print(f"  {m['slug']}: p={f['p_yes']:.2f} → {m.get('resolved_outcome', '?')}")
        if s:
            print(f"    Brier: {s['brier']:.4f}, PnL: {s['pnl_points']:.1f}")
