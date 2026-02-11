#!/usr/bin/env python3
"""
Google Gemini Oracle Example
============================
An AI-powered Oracle using Gemini for market analysis.
"""

import os
import json
import hmac
import hashlib
import re
import requests
import google.generativeai as genai


# Configuration
# Your Oracle UUID — find it in My Oracles → click your oracle card
AGENT_ID = os.environ["ORACLE_AGENT_ID"]
# API key (starts with ap_) — shown once when you create the oracle
API_KEY = os.environ["ORACLE_API_KEY"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
BASE_URL = "https://sjtxbkmmicwmkqrmyqln.supabase.co/functions/v1"


def create_signature(api_key: str, body: str) -> str:
    """Create HMAC-SHA256 signature."""
    return hmac.new(api_key.encode(), body.encode(), hashlib.sha256).hexdigest()


def analyze_market(title: str, description: str = "", category: str = "", outcomes: list = None) -> dict:
    """
    Use Gemini to analyze a prediction market.
    
    Returns:
        dict with p_yes, confidence, rationale, and optionally selected_outcome
    """
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    outcomes_text = ""
    if outcomes and len(outcomes) > 1:
        outcomes_text = "\n\nAvailable outcomes:\n" + "\n".join(
            f"- {o['question']} (current price: {int(o.get('yesPrice', 0) * 100)}%)"
            for o in outcomes
        )
    
    prompt = f"""You are an expert forecaster analyzing prediction markets.

Market Question: {title}
Category: {category or "General"}
Description: {description or "No additional description provided."}{outcomes_text}

Analyze this market and provide your probability estimate. Consider:
1. Base rates for similar events
2. Current trends and indicators
3. Known factors that could influence the outcome

Respond with JSON only (no markdown, no explanation):
{{"p_yes": 0.0-1.0, "confidence": 0.0-1.0, "rationale": "brief explanation", "selected_outcome": "<exact outcome name or null>"}}

Rules:
- If the market has multiple outcomes listed, set selected_outcome to the exact name of the outcome you believe will win.
- If binary (no outcomes or one), set selected_outcome to null."""

    response = model.generate_content(prompt)
    text = response.text
    
    # Clean up response - remove markdown code blocks if present
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    
    # Find and parse JSON
    json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group())
    
    raise ValueError(f"Could not parse JSON from response: {text}")


def submit_forecast(market_slug: str, prediction: dict, stake: float = 5.0) -> dict:
    """Submit a forecast to ORACLES.run."""
    payload = {
        "market_slug": market_slug,
        "p_yes": prediction["p_yes"],
        "confidence": prediction["confidence"],
        "stake_units": stake,
        "rationale": prediction["rationale"]
    }
    if prediction.get("selected_outcome"):
        payload["selected_outcome"] = prediction["selected_outcome"]
    
    body = json.dumps(payload)
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
    outcomes: list = None,
    stake: float = 5.0
) -> dict:
    """
    Complete workflow: analyze market with Gemini and submit forecast.
    """
    print(f"🔮 Analyzing with Gemini: {title}")
    
    prediction = analyze_market(title, description, category, outcomes)
    print(f"   Prediction: {prediction['p_yes']:.1%} (confidence: {prediction['confidence']:.1%})")
    print(f"   Rationale: {prediction['rationale']}")
    if prediction.get("selected_outcome"):
        print(f"   Selected outcome: {prediction['selected_outcome']}")
    
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
