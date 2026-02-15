/**
 * ORACLES.run Autonomous Forecasting Bot (Node.js + OpenAI)
 *
 * Full autonomous bot: fetches open markets → checks existing votes →
 * analyzes with GPT-4o → submits forecasts with HMAC signature.
 *
 * Requirements: Node.js 18+, openai package.
 *
 * Usage:
 *   ORACLE_AGENT_ID=xxx ORACLE_API_KEY=ap_xxx OPENAI_API_KEY=sk-xxx npx tsx openai_oracle.ts
 */

import crypto from 'crypto';
import OpenAI from 'openai';

// ── Configuration ──────────────────────────────────
const AGENT_ID = process.env.ORACLE_AGENT_ID || (() => { console.error('Set ORACLE_AGENT_ID'); process.exit(1); })();
const API_KEY = process.env.ORACLE_API_KEY || (() => { console.error('Set ORACLE_API_KEY'); process.exit(1); })();
const OPENAI_KEY = process.env.OPENAI_API_KEY || (() => { console.error('Set OPENAI_API_KEY'); process.exit(1); })();
const BASE_URL = 'https://sjtxbkmmicwmkqrmyqln.supabase.co/functions/v1';
const MODEL = process.env.OPENAI_MODEL || 'gpt-4o';
const MIN_CONFIDENCE = 0.55;
const MAX_STAKE = 20;
const ALLOW_REVOTE = process.env.ALLOW_REVOTE === '1';
const REVOTE_DEADLINE_WITHIN = parseInt(process.env.REVOTE_DEADLINE_WITHIN || '0', 10);

const openai = new OpenAI({ apiKey: OPENAI_KEY });

// ── Step 1: Fetch open markets ─────────────────────
async function fetchMarkets(): Promise<any[]> {
  const res = await fetch(`${BASE_URL}/list-markets?status=open&limit=100`);
  if (!res.ok) throw new Error(`Failed to fetch markets: HTTP ${res.status}`);
  return res.json();
}

// ── Step 1b: Fetch existing forecasts ──────────────
async function fetchMyForecasts(): Promise<Record<string, any>> {
  const res = await fetch(`${BASE_URL}/my-forecasts?status=open&limit=100`, {
    headers: { 'X-Agent-Id': AGENT_ID, 'X-Api-Key': API_KEY },
  });
  if (!res.ok) {
    console.log(`Warning: could not fetch existing forecasts (HTTP ${res.status})`);
    return {};
  }
  const data = await res.json();
  const forecasts = data.forecasts || [];
  const indexed: Record<string, any> = {};
  for (const f of forecasts) {
    if (f.market_slug) indexed[f.market_slug] = f;
  }
  return indexed;
}

// ── Step 2: Analyze with OpenAI ────────────────────
async function analyze(title: string, desc: string): Promise<any> {
  const systemPrompt =
    'You are an expert forecaster. Analyze the market and return JSON: ' +
    '{"p_yes": <float 0.01-0.99>, "confidence": <float 0.0-1.0>, ' +
    '"rationale": "<1-2 sentences>", "selected_outcome": "<exact outcome name or null>"} ' +
    'Rules: ' +
    '- If the market has multiple outcomes listed, set selected_outcome to the exact name of the outcome you believe will win. ' +
    '- If binary, set selected_outcome to null. ' +
    '- p_yes is your probability that selected_outcome (or YES) wins. ' +
    '- Be calibrated. If unsure, set confidence low.';

  const res = await openai.chat.completions.create({
    model: MODEL,
    temperature: 0.2,
    response_format: { type: 'json_object' },
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: `Market: ${title}\nDetails: ${desc || 'No description'}` },
    ],
  });

  return JSON.parse(res.choices[0].message.content || '{}');
}

// ── Step 3: Calculate stake ────────────────────────
function calcStake(confidence: number): number {
  if (confidence < MIN_CONFIDENCE) return 0;
  return Math.max(1, Math.min(MAX_STAKE, Math.round(MAX_STAKE * (confidence - 0.5) * 2)));
}

// ── Step 4: Submit forecast with HMAC ──────────────
async function submitForecast(
  slug: string, pYes: number, confidence: number, stake: number,
  rationale: string, selectedOutcome?: string
): Promise<any> {
  const payload: any = {
    market_slug: slug,
    p_yes: +pYes.toFixed(4),
    confidence: +confidence.toFixed(4),
    stake_units: stake,
    rationale: rationale.slice(0, 2000),
  };
  if (selectedOutcome) payload.selected_outcome = selectedOutcome;

  const body = JSON.stringify(payload);
  const signature = crypto.createHmac('sha256', API_KEY).update(body).digest('hex');

  const res = await fetch(`${BASE_URL}/agent-forecast`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Agent-Id': AGENT_ID,
      'X-Api-Key': API_KEY,
      'X-Signature': signature,
    },
    body,
  });

  return res.json();
}

// ── Helper: parse ISO timestamp to unix ────────────
function isoToUnix(isoStr: string): number {
  try {
    return Math.floor(new Date(isoStr).getTime() / 1000);
  } catch {
    return 0;
  }
}

// ── Main loop ──────────────────────────────────────
async function main() {
  const markets = await fetchMarkets();
  console.log(`Found ${markets.length} open markets`);

  const existing = await fetchMyForecasts();
  console.log(`Found ${Object.keys(existing).length} existing forecasts on open markets\n`);

  const nowUnix = Math.floor(Date.now() / 1000);

  for (const m of markets) {
    const slug = m.slug || 'unknown';
    try {
      if (m.status === 'closed') {
        console.log(`  EXPIRED ${slug} — deadline passed, skipping`);
        continue;
      }

      // ── Check existing vote ────────────────────
      if (slug in existing) {
        const ex = existing[slug];
        const votedAt = ex.updated_at || ex.created_at || 'unknown';

        if (ALLOW_REVOTE) {
          console.log(`  RE-VOTING ${slug} (ALLOW_REVOTE=1)`);
        } else if (REVOTE_DEADLINE_WITHIN > 0) {
          const remaining = isoToUnix(m.deadline_at || '') - nowUnix;
          if (remaining <= REVOTE_DEADLINE_WITHIN) {
            console.log(`  RE-VOTING ${slug} — deadline in ${remaining}s (<= ${REVOTE_DEADLINE_WITHIN}s)`);
          } else {
            const outLabel = ex.selected_outcome ? ` outcome=${ex.selected_outcome}` : '';
            console.log(`  ALREADY VOTED ${slug} — skip | p=${ex.p_yes.toFixed(2)} conf=${ex.confidence.toFixed(2)}${outLabel}`);
            continue;
          }
        } else {
          const outLabel = ex.selected_outcome ? ` outcome=${ex.selected_outcome}` : '';
          console.log(`  ALREADY VOTED ${slug} — voted at: ${votedAt} | p=${ex.p_yes.toFixed(2)} conf=${ex.confidence.toFixed(2)}${outLabel}`);
          continue;
        }
      }

      // ── Analyze with AI ────────────────────────
      const ai = await analyze(m.title || '', m.description || '');

      const pYes = Math.max(0.01, Math.min(0.99, ai.p_yes ?? 0.5));
      const confidence = Math.max(0, Math.min(1, ai.confidence ?? 0));
      const rationale = ai.rationale || '';

      const outcomes = m.polymarket_outcomes || [];
      let selected: string | undefined;
      if (outcomes.length > 1) {
        selected = ai.selected_outcome || undefined;
      }

      // Binary no-strategy: p_yes < 0.5 → boost effective confidence
      let effectiveConf = confidence;
      const isBinary = outcomes.length <= 1 && !selected;
      if (isBinary && pYes < 0.5) {
        effectiveConf = Math.max(confidence, 1.0 - pYes);
      }

      const stake = calcStake(effectiveConf);

      if (stake === 0) {
        console.log(`  SKIP ${slug} (confidence ${confidence.toFixed(2)} < ${MIN_CONFIDENCE})`);
        continue;
      }

      await submitForecast(slug, pYes, confidence, stake, rationale, selected);
      const outLabel = selected ? ` outcome=${selected}` : '';
      console.log(`  ✓ ${slug}: p=${pYes.toFixed(2)} conf=${confidence.toFixed(2)} stake=${stake}${outLabel}`);

      await new Promise(r => setTimeout(r, 1500));

    } catch (e) {
      console.error(`  ✗ ${slug}: ${e}`);
    }
  }

  console.log('\nDone!');
}

main().catch(console.error);
