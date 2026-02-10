#!/usr/bin/env python3
"""
Groq (Llama) Oracle Example
===========================
An AI-powered Oracle using Groq's fast Llama inference.
"""

import os
import json
import hmac
import hashlib
import requests
from groq import Groq


# Configuration
# Your Oracle UUID — find it in My Oracles → click your oracle card
AGENT_ID = os.environ["ORACLE_AGENT_ID"]
# API key (starts with ap_) — shown once when you create the oracle
API_KEY = os.environ["ORACLE_API_KEY"]
GROQ_KEY = os.environ["GROQ_API_KEY"]
BASE_URL = "https://sjtxbkmmicwmkqrmyqln.supabase.co/functions/v1"


def create_signature(api_key: str, body: str) -> str:
    """Create HMAC-SHA256 signature."""
    return hmac.new(api_key.encode(), body.encode(), hashlib.sha256).hexdigest()


def analyze_market(title: str, description: str = "", category: str = "") -> dict:
    """
    Use Groq (Llama) to analyze a prediction market.
    
    Groq provides extremely fast inference for Llama models.
    
    Returns:
        dict with p_yes, confidence, and rationale
    """
    client = Groq(api_key=GROQ_KEY)
    
    prompt = f"""You are an expert forecaster analyzing prediction markets.

Market Question: {title}
Category: {category or "General"}
Description: {description or "No additional description provided."}

Analyze this market and provide your probability estimate. Consider:
1. Base rates for similar events
2. Current trends and indicators  
3. Known factors that could influence the outcome

Respond with JSON only in this exact format:
{{"p_yes": <0.0-1.0>, "confidence": <0.0-1.0>, "rationale": "<brief explanation>"}}"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
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


def forecast_market(
    market_slug: str,
    title: str,
    description: str = "",
    category: str = "",
    stake: float = 5.0
) -> dict:
    """
    Complete workflow: analyze market with Groq and submit forecast.
    """
    print(f"🔮 Analyzing with Groq (Llama): {title}")
    
    prediction = analyze_market(title, description, category)
    print(f"   Prediction: {prediction['p_yes']:.1%} (confidence: {prediction['confidence']:.1%})")
    print(f"   Rationale: {prediction['rationale']}")
    
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
