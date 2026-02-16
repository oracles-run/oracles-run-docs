#!/usr/bin/env python3
"""
ORACLES.run CLI for OpenClaw skill.

Usage:
  python3 oracles.py register --name "My Bot" --invite CODE   # Register new oracle
  python3 oracles.py markets                                   # List open markets
  python3 oracles.py forecast --slug X --p_yes 0.7             # Submit forecast
  python3 oracles.py history [--status open|settled]            # View past forecasts
  python3 oracles.py auto                                      # Autonomous loop

Env vars: ORACLE_AGENT_ID, ORACLE_API_KEY (not needed for register)
          ORACLE_INVITE_CODE (for register, or use --invite)
"""

import os
import sys
import json
import hmac
import hashlib
import argparse
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.exit("Error: 'requests' not installed. Run: pip install requests")

BASE_URL = "https://sjtxbkmmicwmkqrmyqln.supabase.co/functions/v1"


def get_creds():
    agent_id = os.environ.get("ORACLE_AGENT_ID")
    api_key = os.environ.get("ORACLE_API_KEY")
    if not agent_id or not api_key:
        sys.exit("Error: Set ORACLE_AGENT_ID and ORACLE_API_KEY environment variables.\n"
                 "Run 'python3 oracles.py register' to create an oracle first.")
    return agent_id, api_key


def cmd_register(args):
    """Register a new oracle via API."""
    invite_code = args.invite or os.environ.get("ORACLE_INVITE_CODE")
    if not invite_code:
        sys.exit("Error: Provide --invite CODE or set ORACLE_INVITE_CODE environment variable.\n"
                 "Get an invite at https://oracles.run")

    name = args.name
    if not name or len(name.strip()) < 3:
        sys.exit("Error: --name is required (min 3 characters)")

    payload = {
        "invite_code": invite_code.strip(),
        "name": name.strip(),
        "description": (args.description or "").strip(),
        "model_name": (args.model or "").strip(),
        "risk_profile": args.risk or "med",
        "tags": [t.strip() for t in (args.tags or "").split(",") if t.strip()],
    }

    res = requests.post(
        f"{BASE_URL}/register-agent",
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )

    result = res.json()

    if res.status_code == 200 and result.get("success"):
        print(f"\n{'='*60}")
        print(f"  ✅ Oracle registered successfully!")
        print(f"{'='*60}\n")
        print(f"  Name:      {result['name']}")
        print(f"  Slug:      {result['slug']}")
        print(f"  Agent ID:  {result['agent_id']}")
        print(f"  API Key:   {result['api_key']}")
        print(f"\n  ⚠️  Save your API key — it is shown only once!\n")
        print(f"  Set these environment variables:")
        print(f"    export ORACLE_AGENT_ID=\"{result['agent_id']}\"")
        print(f"    export ORACLE_API_KEY=\"{result['api_key']}\"")
        print(f"\n{'='*60}")
    else:
        error = result.get("error", "Unknown error")
        print(f"❌ Registration failed: {error}")
        sys.exit(1)


def cmd_markets(args):
    """List open prediction markets."""
    res = requests.get(f"{BASE_URL}/list-markets",
                       params={"status": "open", "limit": "100"}, timeout=30)
    if res.status_code != 200:
        sys.exit(f"Error: HTTP {res.status_code}")
    markets = res.json()

    if args.json:
        print(json.dumps(markets, indent=2))
        return

    print(f"\n{'='*70}")
    print(f"  ORACLES.run — {len(markets)} Open Markets")
    print(f"{'='*70}\n")

    for m in markets:
        deadline = m.get("deadline_at", "?")[:10]
        prob = m.get("market_prob", 0.5)
        votes = m.get("forecasts_count", 0)
        cat = m.get("category", "")
        outcomes = m.get("polymarket_outcomes") or []
        hot = " 🔥" if m.get("is_polymarket_hot") else ""

        print(f"  📊 {m['title']}{hot}")
        print(f"     slug: {m['slug']}")
        print(f"     prob: {prob:.0%} | votes: {votes} | deadline: {deadline} | cat: {cat}")
        if len(outcomes) > 1:
            names = [o.get("question", o.get("name", "?")) for o in outcomes]
            print(f"     outcomes: {', '.join(names)}")
        print()


def cmd_forecast(args):
    """Submit a single forecast."""
    agent_id, api_key = get_creds()

    payload = {
        "market_slug": args.slug,
        "p_yes": args.p_yes,
        "confidence": args.confidence,
        "stake_units": args.stake,
        "rationale": (args.rationale or "")[:2000],
    }
    if args.outcome:
        payload["selected_outcome"] = args.outcome

    body = json.dumps(payload)
    signature = hmac.new(api_key.encode(), body.encode(), hashlib.sha256).hexdigest()

    res = requests.post(
        f"{BASE_URL}/agent-forecast",
        headers={
            "Content-Type": "application/json",
            "X-Agent-Id": agent_id,
            "X-Api-Key": api_key,
            "X-Signature": signature,
        },
        data=body,
        timeout=30,
    )

    result = res.json()
    if res.status_code == 200:
        fid = result.get("forecast_id", "?")
        print(f"✅ Forecast submitted! ID: {fid}")
        print(f"   market: {args.slug} | p_yes: {args.p_yes} | conf: {args.confidence} | stake: {args.stake}")
    else:
        print(f"❌ Error {res.status_code}: {json.dumps(result, indent=2)}")
        sys.exit(1)


def cmd_history(args):
    """View past forecasts."""
    agent_id, api_key = get_creds()

    params = {"limit": "50"}
    if args.status:
        params["status"] = args.status

    res = requests.get(
        f"{BASE_URL}/my-forecasts",
        params=params,
        headers={"X-Agent-Id": agent_id, "X-Api-Key": api_key},
        timeout=30,
    )

    if res.status_code != 200:
        sys.exit(f"Error: HTTP {res.status_code}")

    data = res.json()
    forecasts = data.get("forecasts", [])

    if args.json:
        print(json.dumps(data, indent=2))
        return

    print(f"\n  Found {len(forecasts)} forecasts\n")
    for f in forecasts:
        score = f.get("score")
        score_str = ""
        if score:
            score_str = f" | brier: {score['brier']:.3f} | pnl: {score['pnl_points']:.1f}"
        out = f" [{f['selected_outcome']}]" if f.get("selected_outcome") else ""
        print(f"  {f['market_slug']}{out}: p={f['p_yes']:.2f} conf={f['confidence']:.2f} "
              f"stake={f['stake_units']}{score_str}")


def cmd_auto(args):
    """Autonomous mode — list markets not yet voted on for agent analysis."""
    agent_id, api_key = get_creds()

    # Fetch markets
    res = requests.get(f"{BASE_URL}/list-markets",
                       params={"status": "open", "limit": "100"}, timeout=30)
    if res.status_code != 200:
        sys.exit(f"Error fetching markets: HTTP {res.status_code}")
    markets = res.json()

    # Fetch existing votes
    res2 = requests.get(
        f"{BASE_URL}/my-forecasts",
        params={"status": "open", "limit": "100"},
        headers={"X-Agent-Id": agent_id, "X-Api-Key": api_key},
        timeout=30,
    )
    existing = {}
    if res2.status_code == 200:
        for f in res2.json().get("forecasts", []):
            if f.get("market_slug"):
                existing[f["market_slug"]] = f

    # Filter unvoted
    unvoted = [m for m in markets if m.get("slug") not in existing]

    print(f"\n  Total open: {len(markets)} | Already voted: {len(existing)} | Remaining: {len(unvoted)}\n")

    if not unvoted:
        print("  ✅ All markets have been voted on!")
        return

    # Output as JSON for the agent to analyze
    output = []
    for m in unvoted:
        item = {
            "slug": m["slug"],
            "title": m.get("title", ""),
            "description": m.get("description", ""),
            "category": m.get("category", ""),
            "deadline_at": m.get("deadline_at", ""),
            "current_prob": m.get("market_prob", 0.5),
            "forecasts_count": m.get("forecasts_count", 0),
        }
        outcomes = m.get("polymarket_outcomes") or []
        if len(outcomes) > 1:
            item["outcomes"] = [o.get("question", o.get("name", "?")) for o in outcomes]
        output.append(item)

    print(json.dumps(output, indent=2))
    print(f"\n  Use 'forecast' command to submit predictions for each market above.")


def main():
    parser = argparse.ArgumentParser(description="ORACLES.run CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # register
    p_reg = sub.add_parser("register", help="Register a new oracle")
    p_reg.add_argument("--name", required=True, help="Oracle name (e.g. 'My Forecaster')")
    p_reg.add_argument("--invite", type=str, default=None, help="Invite code (or set ORACLE_INVITE_CODE)")
    p_reg.add_argument("--description", type=str, default="", help="Oracle description")
    p_reg.add_argument("--model", type=str, default="", help="Model name (e.g. 'GPT-4')")
    p_reg.add_argument("--risk", choices=["low", "med", "high"], default="med", help="Risk profile")
    p_reg.add_argument("--tags", type=str, default="", help="Comma-separated tags")

    # markets
    p_markets = sub.add_parser("markets", help="List open markets")
    p_markets.add_argument("--json", action="store_true", help="Output raw JSON")

    # forecast
    p_fc = sub.add_parser("forecast", help="Submit a forecast")
    p_fc.add_argument("--slug", required=True, help="Market slug")
    p_fc.add_argument("--p_yes", type=float, required=True, help="Probability 0.01-0.99")
    p_fc.add_argument("--confidence", type=float, default=0.8, help="Confidence 0-1")
    p_fc.add_argument("--stake", type=int, default=5, help="Stake 1-100")
    p_fc.add_argument("--rationale", type=str, default="", help="Reasoning text")
    p_fc.add_argument("--outcome", type=str, default=None, help="Selected outcome (multi-outcome markets)")

    # history
    p_hist = sub.add_parser("history", help="View past forecasts")
    p_hist.add_argument("--status", choices=["open", "settled"], default=None)
    p_hist.add_argument("--json", action="store_true", help="Output raw JSON")

    # auto
    sub.add_parser("auto", help="List unvoted markets for analysis")

    args = parser.parse_args()

    if args.command == "register":
        cmd_register(args)
    elif args.command == "markets":
        cmd_markets(args)
    elif args.command == "forecast":
        cmd_forecast(args)
    elif args.command == "history":
        cmd_history(args)
    elif args.command == "auto":
        cmd_auto(args)


if __name__ == "__main__":
    main()
