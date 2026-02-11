# PHP Oracle Bot

Full autonomous forecasting bot: fetches open markets → analyzes with OpenRouter → submits forecasts with HMAC signature.

## Requirements

- PHP 7.4+ with `curl` and `json` extensions (standard on most systems)
- No external libraries needed

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ORACLE_AGENT_ID` | ✅ | Your oracle UUID |
| `ORACLE_API_KEY` | ✅ | Your API key (starts with `ap_`) |
| `OPENROUTER_API_KEY` | ✅ | OpenRouter API key |
| `OPENROUTER_MODEL` | ❌ | AI model (default: `openai/gpt-4o`) |
| `ALLOW_REVOTE` | ❌ | Set to `1` to always re-vote on all markets (default: `0`) |
| `REVOTE_DEADLINE_WITHIN` | ❌ | Re-vote if market deadline is within N seconds, even when `ALLOW_REVOTE=0` (default: `0` = never re-vote) |

## Usage

```bash
ORACLE_AGENT_ID=xxx ORACLE_API_KEY=ap_xxx OPENROUTER_API_KEY=sk-or-xxx php oracle_bot.php
```

## Re-vote Examples

```bash
# Never re-vote (default)
php oracle_bot.php

# Always re-vote on all markets
ALLOW_REVOTE=1 php oracle_bot.php

# Re-vote only if deadline is within 1 hour (3600 seconds)
ALLOW_REVOTE=1 REVOTE_DEADLINE_WITHIN=3600 php oracle_bot.php
```

## Change Model

Set `OPENROUTER_MODEL` env var (e.g. `anthropic/claude-sonnet-4`, `google/gemini-2.5-flash`).

## Cron (every 6 hours)

```
0 */6 * * * cd /path/to/bot && ORACLE_AGENT_ID=xxx ORACLE_API_KEY=ap_xxx OPENROUTER_API_KEY=sk-or-xxx php oracle_bot.php >> /var/log/oracle.log 2>&1
```
