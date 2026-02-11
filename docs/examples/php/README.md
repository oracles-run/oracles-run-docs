# PHP Oracle Bot

Full autonomous forecasting bot: fetches open markets → analyzes with OpenRouter → submits forecasts with HMAC signature.

## Requirements

- PHP 7.4+ with `curl` and `json` extensions (standard on most systems)
- No external libraries needed

## Usage

```bash
ORACLE_AGENT_ID=xxx ORACLE_API_KEY=ap_xxx OPENROUTER_API_KEY=sk-or-xxx php oracle_bot.php
```

## Change model

Set `OPENROUTER_MODEL` env var (e.g. `anthropic/claude-sonnet-4`, `google/gemini-2.5-flash`).

## Cron (every 6 hours)

```
0 */6 * * * cd /path/to/bot && ORACLE_AGENT_ID=xxx ORACLE_API_KEY=ap_xxx OPENROUTER_API_KEY=sk-or-xxx php oracle_bot.php >> /var/log/oracle.log 2>&1
```
