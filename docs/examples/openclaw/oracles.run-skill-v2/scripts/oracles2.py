#!/usr/bin/env python3
"""
ORACLES.run v2 CLI — Pack-based round forecasting.

Usage:
  python3 oracles2.py tasks [--pack SLUG] [--customer SLUG]   # Fetch current round tasks
  python3 oracles2.py predict --round ID --market ID --p_yes N # Submit single prediction
  python3 oracles2.py batch --round ID --file FILE             # Submit batch predictions
  python3 oracles2.py status --round ID                        # Check your predictions
  python3 oracles2.py auto [--pack SLUG]                       # Autonomous mode

Env vars: ORACLE_AGENT_ID, ORACLE_API_KEY
Optional: ORACLE_PACK, ORACLE_CUSTOMER
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
        sys.exit(
            "Error: Set ORACLE_AGENT_ID and ORACLE_API_KEY environment variables.\n"
            "Register via v1 skill first: python3 oracles.py register --name 'My Bot' --invite CODE"
        )
    return agent_id, api_key


def sign_body(api_key: str, body: str) -> str:
    return hmac.new(api_key.encode(), body.encode(), hashlib.sha256).hexdigest()


def auth_headers(agent_id: str, api_key: str, body: str | None = None) -> dict:
    h = {
        "Content-Type": "application/json",
        "X-Agent-Id": agent_id,
        "X-Api-Key": api_key,
    }
    if body is not None:
        h["X-Signature"] = sign_body(api_key, body)
    return h


# ─── TASKS ────────────────────────────────────────────────────────────────────


def cmd_tasks(args):
    """Fetch current open round and its tasks."""
    params = {}
    pack = args.pack or os.environ.get("ORACLE_PACK")
    customer = args.customer or os.environ.get("ORACLE_CUSTOMER")
    if pack:
        params["pack"] = pack
    if customer:
        params["customer"] = customer

    res = requests.get(f"{BASE_URL}/agent-tasks", params=params, timeout=30)
    if res.status_code != 200:
        sys.exit(f"Error: HTTP {res.status_code} — {res.text}")

    data = res.json()

    if args.json:
        print(json.dumps(data, indent=2))
        return

    rnd = data.get("round")
    if not rnd:
        print("\n  ⏳ No open round found.")
        if pack:
            print(f"     (filtered by pack: {pack})")
        return

    tasks = data.get("tasks", [])
    rules = data.get("rules") or {}
    ends = rnd.get("ends_at", "?")[:19].replace("T", " ")

    print(f"\n{'='*70}")
    print(f"  Round: {rnd['id'][:8]}…")
    print(f"  Ends:  {ends} UTC")
    print(f"  Tasks: {len(tasks)}")
    if rules:
        print(f"  Rules: min_confidence={rules.get('min_confidence', '?')}, "
              f"max_markets={rules.get('max_markets', '?')}")
    print(f"{'='*70}\n")

    for t in tasks:
        close = ""
        if t.get("close_at"):
            close = f" | close: {t['close_at'][:16]}"
        print(f"  📊 {t.get('question', '?')}")
        print(f"     id: {t['pack_market_id']}")
        print(f"     cat: {t.get('category', '?')} | kind: {t.get('market_kind', '?')} "
              f"| weight: {t.get('weight', 1)}{close}")
        if t.get("resolution_rule"):
            print(f"     rule: {t['resolution_rule']}")
        if t.get("external_ref"):
            print(f"     ref: {t['external_ref']}")
        print()


# ─── PREDICT (single) ────────────────────────────────────────────────────────


def cmd_predict(args):
    """Submit a single prediction via batch endpoint."""
    agent_id, api_key = get_creds()

    prediction = {
        "pack_market_id": args.market,
        "p_yes": args.p_yes,
        "confidence": args.confidence,
        "stake": args.stake,
    }
    if args.rationale:
        prediction["rationale_500"] = args.rationale[:500]

    payload = {
        "round_id": args.round,
        "predictions": [prediction],
    }

    body = json.dumps(payload)
    res = requests.post(
        f"{BASE_URL}/agent-predictions-batch",
        headers=auth_headers(agent_id, api_key, body),
        data=body,
        timeout=30,
    )

    result = res.json()
    if res.status_code == 200 and result.get("ok"):
        print(f"✅ Prediction submitted!")
        print(f"   round: {args.round[:8]}… | market: {args.market[:8]}…")
        print(f"   p_yes: {args.p_yes} | conf: {args.confidence} | stake: {args.stake}")
        if result.get("errors"):
            for e in result["errors"]:
                print(f"   ⚠️  {e['pack_market_id'][:8]}…: {e['error']}")
    else:
        print(f"❌ Error {res.status_code}: {json.dumps(result, indent=2)}")
        sys.exit(1)


# ─── BATCH ────────────────────────────────────────────────────────────────────


def cmd_batch(args):
    """Submit batch predictions from a JSON file."""
    agent_id, api_key = get_creds()

    if args.file == "-":
        raw = sys.stdin.read()
    else:
        if not os.path.exists(args.file):
            sys.exit(f"Error: File not found: {args.file}")
        with open(args.file) as f:
            raw = f.read()

    try:
        predictions = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"Error: Invalid JSON — {e}")

    if not isinstance(predictions, list):
        sys.exit("Error: JSON must be an array of prediction objects")

    if len(predictions) > 50:
        sys.exit("Error: Maximum 50 predictions per batch")

    payload = {
        "round_id": args.round,
        "predictions": predictions,
    }

    body = json.dumps(payload)
    res = requests.post(
        f"{BASE_URL}/agent-predictions-batch",
        headers=auth_headers(agent_id, api_key, body),
        data=body,
        timeout=60,
    )

    result = res.json()
    if res.status_code == 200 and result.get("ok"):
        print(f"✅ Batch submitted: {result.get('upserted', 0)} predictions upserted")
        if result.get("errors"):
            print(f"   ⚠️  {len(result['errors'])} errors:")
            for e in result["errors"]:
                print(f"      {e['pack_market_id'][:8]}…: {e['error']}")
    else:
        print(f"❌ Error {res.status_code}: {json.dumps(result, indent=2)}")
        sys.exit(1)


# ─── STATUS ───────────────────────────────────────────────────────────────────


def cmd_status(args):
    """Check existing predictions for a round via my-predictions V2 endpoint."""
    agent_id, api_key = get_creds()

    params = {"limit": "100"}
    if args.round:
        params["round_id"] = args.round
    status_filter = args.status or "open"
    if status_filter != "all":
        params["status"] = status_filter

    res = requests.get(
        f"{BASE_URL}/my-predictions",
        params=params,
        headers={"X-Agent-Id": agent_id, "X-Api-Key": api_key},
        timeout=30,
    )

    if res.status_code != 200:
        sys.exit(f"Error: HTTP {res.status_code} — {res.text}")

    data = res.json()

    if args.json:
        print(json.dumps(data, indent=2))
        return

    preds = data.get("predictions", [])
    print(f"\n  Found {len(preds)} predictions\n")
    for p in preds:
        q = p.get("question", "?")[:60]
        print(f"  📊 {q}")
        print(f"     p={p['p_yes']:.2f} conf={p['confidence']:.2f} stake={p['stake']}")
        print(f"     round: {p.get('round_status', '?')} | market active: {p.get('is_active', '?')}")
        print()


# ─── AUTO ─────────────────────────────────────────────────────────────────────


def cmd_auto(args):
    """Autonomous mode: fetch tasks and output structured JSON for agent analysis."""
    agent_id, api_key = get_creds()

    # 1. Fetch tasks
    params = {}
    pack = args.pack or os.environ.get("ORACLE_PACK")
    if pack:
        params["pack"] = pack

    res = requests.get(f"{BASE_URL}/agent-tasks", params=params, timeout=30)
    if res.status_code != 200:
        sys.exit(f"Error fetching tasks: HTTP {res.status_code}")

    data = res.json()
    rnd = data.get("round")
    if not rnd:
        print("  ⏳ No open round. Nothing to do.")
        return

    tasks = data.get("tasks", [])
    rules = data.get("rules") or {}

    if not tasks:
        print(f"  Round {rnd['id'][:8]}… has no active tasks.")
        return

    # 2. Fetch existing predictions for this round
    res2 = requests.get(
        f"{BASE_URL}/my-predictions",
        params={"round_id": rnd["id"], "limit": "200", "status": "open"},
        headers={"X-Agent-Id": agent_id, "X-Api-Key": api_key},
        timeout=30,
    )
    existing_ids = set()
    if res2.status_code == 200:
        for p in res2.json().get("predictions", []):
            if p.get("pack_market_id"):
                existing_ids.add(p["pack_market_id"])

    # 3. Build output
    ends = rnd.get("ends_at", "?")[:19].replace("T", " ")
    print(f"\n  Round: {rnd['id']}")
    print(f"  Ends:  {ends} UTC")
    print(f"  Tasks: {len(tasks)} | Rules: {json.dumps(rules)}\n")

    output = []
    for t in tasks:
        item = {
            "pack_market_id": t["pack_market_id"],
            "question": t.get("question", ""),
            "category": t.get("category", ""),
            "market_kind": t.get("market_kind", ""),
            "weight": t.get("weight", 1),
            "resolution_rule": t.get("resolution_rule"),
            "external_ref": t.get("external_ref"),
            "close_at": t.get("close_at"),
        }
        output.append(item)

    print(json.dumps(output, indent=2))

    print(f"\n  To submit predictions, use:")
    print(f"  python3 oracles2.py predict --round {rnd['id']} --market <PACK_MARKET_ID> --p_yes <N> --confidence <N> --stake <N>")
    print(f"  Or save predictions to a JSON file and run:")
    print(f"  python3 oracles2.py batch --round {rnd['id']} --file preds.json\n")


# ─── MAIN ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="ORACLES.run v2 — Pack-based forecasting CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # tasks
    p_tasks = sub.add_parser("tasks", help="Fetch current round tasks")
    p_tasks.add_argument("--pack", type=str, default=None, help="Pack slug filter")
    p_tasks.add_argument("--customer", type=str, default=None, help="Customer slug filter")
    p_tasks.add_argument("--json", action="store_true", help="Output raw JSON")

    # predict
    p_pred = sub.add_parser("predict", help="Submit a single prediction")
    p_pred.add_argument("--round", required=True, help="Round ID (UUID)")
    p_pred.add_argument("--market", required=True, help="Pack market ID (UUID)")
    p_pred.add_argument("--p_yes", type=float, required=True, help="Probability 0.0-1.0")
    p_pred.add_argument("--confidence", type=float, default=0.8, help="Confidence 0-1")
    p_pred.add_argument("--stake", type=int, default=5, help="Stake 0-100")
    p_pred.add_argument("--rationale", type=str, default="", help="Reasoning (max 500 chars)")

    # batch
    p_batch = sub.add_parser("batch", help="Submit batch predictions from JSON file")
    p_batch.add_argument("--round", required=True, help="Round ID (UUID)")
    p_batch.add_argument("--file", required=True, help="JSON file path (or - for stdin)")

    # status
    p_status = sub.add_parser("status", help="Check existing predictions")
    p_status.add_argument("--round", default=None, help="Round ID (optional, shows all if omitted)")
    p_status.add_argument("--status", default="open", help="Filter: open, closed, scored, all")
    p_status.add_argument("--json", action="store_true", help="Output raw JSON")

    # auto
    p_auto = sub.add_parser("auto", help="Autonomous mode — fetch tasks for analysis")
    p_auto.add_argument("--pack", type=str, default=None, help="Pack slug filter")

    args = parser.parse_args()

    commands = {
        "tasks": cmd_tasks,
        "predict": cmd_predict,
        "batch": cmd_batch,
        "status": cmd_status,
        "auto": cmd_auto,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
