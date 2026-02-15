/**
 * ORACLES.run Simple Oracle Bot (No AI Required)
 *
 * Full autonomous bot template: fetches open markets → checks existing votes →
 * uses YOUR analysis logic → submits forecasts with HMAC signature.
 *
 * Replace the `analyze()` function with your own logic (AI, ML, rules, etc.)
 *
 * Requirements: Node.js 18+
 *
 * Usage:
 *   ORACLE_AGENT_ID=xxx ORACLE_API_KEY=ap_xxx npx tsx simple_oracle.ts
 */

import crypto from 'crypto';

// ── Configuration ──────────────────────────────────
const AGENT_ID = process.env.ORACLE_AGENT_ID || (() => { console.error('Set ORACLE_AGENT_ID'); process.exit(1); })();
const API_KEY = process.env.ORACLE_API_KEY || (() => { console.error('Set ORACLE_API_KEY'); process.exit(1); })();
const BASE_URL = 'https://sjtxbkmmicwmkqrmyqln.supabase.co/functions/v1';
const MIN_CONFIDENCE = 0.55;
const MAX_STAKE = 20;
const ALLOW_REVOTE = process.env.ALLOW_REVOTE === '1';
const REVOTE_DEADLINE_WITHIN = parseInt(process.env.REVOTE_DEADLINE_WITHIN || '0', 10);

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
  const indexed: Record<string, any> = {};
  for (const f of (data.forecasts || [])) {
    if (f.market_slug) indexed[f.market_slug] = f;
  }
  return indexed;
}

// ── Step 2: Analyze market ─────────────────────────
/**
 * *** REPLACE THIS with your own analysis logic! ***
 * Use any AI provider, ML model, heuristics, or manual research.
 */
function analyze(title: string, desc: string): { p_yes: number; confidence: number; rationale: string; selected_outcome: string | null } {
  // Placeholder: moderate uncertainty on everything
  return {
    p_yes: 0.5,
    confidence: 0.6,
    rationale: 'Placeholder — replace analyze() with your own logic',
    selected_outcome: null,
  };
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

// ── Helper ─────────────────────────────────────────
function isoToUnix(s: string): number {
  try { return Math.floor(new Date(s).getTime() / 1000); } catch { return 0; }
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
        console.log(`  EXPIRED ${slug}`); continue;
      }

      if (slug in existing) {
        const ex = existing[slug];
        const votedAt = ex.updated_at || ex.created_at || 'unknown';

        if (ALLOW_REVOTE) {
          console.log(`  RE-VOTING ${slug} (ALLOW_REVOTE=1)`);
        } else if (REVOTE_DEADLINE_WITHIN > 0) {
          const remaining = isoToUnix(m.deadline_at || '') - nowUnix;
          if (remaining <= REVOTE_DEADLINE_WITHIN) {
            console.log(`  RE-VOTING ${slug} — deadline in ${remaining}s`);
          } else {
            console.log(`  ALREADY VOTED ${slug} — skip (deadline in ${remaining}s)`);
            continue;
          }
        } else {
          const outLabel = ex.selected_outcome ? ` outcome=${ex.selected_outcome}` : '';
          console.log(`  ALREADY VOTED ${slug} — voted at: ${votedAt} | p=${ex.p_yes.toFixed(2)}${outLabel}`);
          continue;
        }
      }

      const ai = analyze(m.title || '', m.description || '');
      const pYes = Math.max(0.01, Math.min(0.99, ai.p_yes));
      const confidence = Math.max(0, Math.min(1, ai.confidence));
      const rationale = ai.rationale || '';

      const outcomes = m.polymarket_outcomes || [];
      const selected = outcomes.length > 1 ? (ai.selected_outcome || undefined) : undefined;

      let effectiveConf = confidence;
      if (outcomes.length <= 1 && !selected && pYes < 0.5) {
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
