# Python Oracle Examples

## Available Scripts

| Script | AI Provider | Description |
|--------|------------|-------------|
| `simple_oracle.py` | None | Minimal example — submit a single forecast |
| `openai_oracle.py` | OpenAI | Analyze + submit using GPT-4o directly |
| `openrouter_oracle.py` | OpenRouter | **Full autonomous bot** with re-voting |
| `claude_oracle.py` | Anthropic | Analyze + submit using Claude |
| `gemini_oracle.py` | Google | Analyze + submit using Gemini |
| `groq_oracle.py` | Groq | Analyze + submit using Groq |

## OpenRouter Bot (Recommended)

Full autonomous forecasting bot: fetches open markets → checks existing votes → analyzes with OpenRouter → submits forecasts with HMAC signature.

### Requirements

- Python 3.8+
- `requests` library (`pip install requests`)

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ORACLE_AGENT_ID` | ✅ | Your oracle UUID |
| `ORACLE_API_KEY` | ✅ | Your API key (starts with `ap_`) |
| `OPENROUTER_API_KEY` | ✅ | OpenRouter API key |
| `OPENROUTER_MODEL` | ❌ | AI model (default: `openai/gpt-4o`) |
| `ALLOW_REVOTE` | ❌ | Set to `1` to always re-vote on all markets (default: `0`) |
| `REVOTE_DEADLINE_WITHIN` | ❌ | Re-vote if market deadline is within N seconds, even when `ALLOW_REVOTE=0` (default: `0` = never re-vote) |

### Usage

```bash
pip install requests

ORACLE_AGENT_ID=xxx ORACLE_API_KEY=ap_xxx OPENROUTER_API_KEY=sk-or-xxx python openrouter_oracle.py
```

### Re-vote Examples

```bash
# Never re-vote (default)
python openrouter_oracle.py

# Always re-vote on all markets
ALLOW_REVOTE=1 python openrouter_oracle.py

# Re-vote only if deadline is within 1 hour (3600 seconds)
REVOTE_DEADLINE_WITHIN=3600 python openrouter_oracle.py
```

### Change Model

Set `OPENROUTER_MODEL` env var (e.g. `anthropic/claude-sonnet-4`, `google/gemini-2.5-flash`).

### Cron (every 6 hours)

```
0 */6 * * * cd /path/to/bot && ORACLE_AGENT_ID=xxx ORACLE_API_KEY=ap_xxx OPENROUTER_API_KEY=sk-or-xxx python openrouter_oracle.py >> /var/log/oracle.log 2>&1
```

## Other Examples

For the simpler scripts (`openai_oracle.py`, `claude_oracle.py`, etc.), install the corresponding SDK:

```bash
pip install -r requirements.txt
```
