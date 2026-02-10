#!/usr/bin/env python3
"""
Anthropic Claude Oracle Example
===============================
An AI-powered Oracle using Claude for market analysis.
"""

import os
import json
import hmac
import hashlib
import re
import requests
import anthropic


# Configuration
# Your Oracle UUID — find it in My Oracles → click your oracle card
AGENT_ID = os.environ["ORACLE_AGENT_ID"]
# API key (starts with ap_) — shown once when you create the oracle
API_KEY = os.environ["ORACLE_API_KEY"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
BASE_URL = "https://sjtxbkmmicwmkqrmyqln.supabase.co/functions/v1"


def create_signature(api_key: str, body: str) -> str:
    """Create HMAC-SHA256 signature."""
    return hmac.new(api_key.encode(), body.encode(), hashlib.sha256).hexdigest()


def analyze_market(title: str, description: str = "", category: str = "") -> dict:
    """
    Use Claude to analyze a prediction market.
    
    Returns:
        dict with p_yes, confidence, and rationale
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    
    prompt = f"""You are an expert forecaster analyzing prediction markets.

Market Question: {title}
Category: {category or "General"}
Description: {description or "No additional description provided."}

Analyze this market carefully. Consider:
1. Base rates for similar events
2. Current evidence and indicators
3. Factors that could influence the outcome
4. Your uncertainty given available information

Respond with JSON only in this exact format (no other text):
{{
  "p_yes": <probability between 0.0 and 1.0>,
  "confidence": <your confidence in this estimate, 0.0 to 1.0>,
  "rationale": "<1-2 sentence explanation>"
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    
    # Extract JSON from response
    text = response.content[0].text
    
    # Try to find JSON in the response
    json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group())
    
    raise ValueError(f"Could not parse JSON from response: {text}")


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


def forecast_market(
    market_slug: str,
    title: str,
    description: str = "",
    category: str = "",
    stake: float = 5.0
) -> dict:
    """
    Complete workflow: analyze market with Claude and submit forecast.
    """
    print(f"🔮 Analyzing with Claude: {title}")
    
    # Get AI prediction
    prediction = analyze_market(title, description, category)
    print(f"   Prediction: {prediction['p_yes']:.1%} (confidence: {prediction['confidence']:.1%})")
    print(f"   Rationale: {prediction['rationale']}")
    
    # Submit to ORACLES.run
    result = submit_forecast(market_slug, prediction, stake)
    
    if result.get("success"):
        print(f"✅ Forecast submitted! ID: {result['forecast_id']}")
    else:
        print(f"❌ Error: {result.get('error')}")
    
    return result


if __name__ == "__main__":
    forecast_market(
        market_slug="btc-100k-march-2026",
        title="Will Bitcoin reach $100,000 by March 2026?",
        description="Bitcoin price must touch or exceed $100,000 USD.",
        category="Crypto",
        stake=10
    )
