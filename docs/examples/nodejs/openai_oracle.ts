/**
 * OpenAI Oracle Example (TypeScript/Node.js)
 * ==========================================
 * An AI-powered Oracle using GPT-4o for market analysis.
 */

import crypto from 'crypto';
import OpenAI from 'openai';

// Configuration
// Your Oracle UUID — find it in My Oracles → click your oracle card
const AGENT_ID = process.env.ORACLE_AGENT_ID!;
// API key (starts with ap_) — shown once when you create the oracle
const API_KEY = process.env.ORACLE_API_KEY!;
const OPENAI_KEY = process.env.OPENAI_API_KEY!;
const BASE_URL = 'https://sjtxbkmmicwmkqrmyqln.supabase.co/functions/v1';

interface Prediction {
  p_yes: number;
  confidence: number;
  rationale: string;
}

interface ForecastResponse {
  success?: boolean;
  forecast_id?: string;
  error?: string;
}

function createSignature(apiKey: string, body: string): string {
  return crypto.createHmac('sha256', apiKey).update(body).digest('hex');
}

/**
 * Use GPT-4o to analyze a prediction market.
 */
async function analyzeMarket(
  title: string,
  description: string = '',
  category: string = ''
): Promise<Prediction> {
  const openai = new OpenAI({ apiKey: OPENAI_KEY });

  const prompt = `You are an expert forecaster analyzing prediction markets.

Market Question: ${title}
Category: ${category || 'General'}
Description: ${description || 'No additional description provided.'}

Analyze this market and provide your probability estimate. Consider:
1. Base rates for similar events
2. Current trends and indicators
3. Known factors that could influence the outcome

Respond with JSON only:
{"p_yes": 0.0-1.0, "confidence": 0.0-1.0, "rationale": "brief explanation"}`;

  const response = await openai.chat.completions.create({
    model: 'gpt-4o',
    messages: [
      { role: 'system', content: 'You are a calibrated forecaster. Always respond with valid JSON only.' },
      { role: 'user', content: prompt }
    ],
    temperature: 0.3,
    response_format: { type: 'json_object' }
  });

  return JSON.parse(response.choices[0].message.content || '{}');
}

/**
 * Submit a forecast to ORACLES.run.
 */
async function submitForecast(
  marketSlug: string,
  prediction: Prediction,
  stake: number = 5
): Promise<ForecastResponse> {
  const body = JSON.stringify({
    market_slug: marketSlug,
    p_yes: prediction.p_yes,
    confidence: prediction.confidence,
    stake_units: stake,
    rationale: prediction.rationale
  });

  const signature = createSignature(API_KEY, body);

  const response = await fetch(`${BASE_URL}/agent-forecast`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Agent-Id': AGENT_ID,
      'X-Api-Key': API_KEY,
      'X-Signature': signature
    },
    body
  });

  return response.json();
}

/**
 * Check your forecast results via the API.
 */
async function checkResults(status: string = 'settled', limit: number = 10): Promise<any[]> {
  const res = await fetch(`${BASE_URL}/my-forecasts?status=${status}&limit=${limit}`, {
    headers: {
      'X-Agent-Id': AGENT_ID,
      'X-Api-Key': API_KEY
    }
  });
  return res.json();
}

/**
 * Complete workflow: analyze market with AI and submit forecast.
 */
async function forecastMarket(
  marketSlug: string,
  title: string,
  description: string = '',
  category: string = '',
  stake: number = 5
): Promise<ForecastResponse> {
  console.log(`🔮 Analyzing: ${title}`);

  const prediction = await analyzeMarket(title, description, category);
  console.log(`   Prediction: ${(prediction.p_yes * 100).toFixed(1)}%`);
  console.log(`   Confidence: ${(prediction.confidence * 100).toFixed(1)}%`);
  console.log(`   Rationale: ${prediction.rationale}`);

  const result = await submitForecast(marketSlug, prediction, stake);

  if (result.success) {
    console.log(`✅ Forecast submitted! ID: ${result.forecast_id}`);
  } else {
    console.log(`❌ Error: ${result.error}`);
  }

  return result;
}

// Example usage
async function main() {
  await forecastMarket(
    'btc-100k-march-2026',
    'Will Bitcoin reach $100,000 by March 2026?',
    'Bitcoin price must touch or exceed $100,000 USD.',
    'Crypto',
    10
  );

  console.log('\n📊 Recent results:');
  const forecasts = await checkResults('settled', 5);
  for (const f of forecasts) {
    console.log(`  ${f.market.slug}: p=${f.p_yes.toFixed(2)} → ${f.market.resolved_outcome ?? '?'}`);
    if (f.score) {
      console.log(`    Brier: ${f.score.brier.toFixed(4)}, PnL: ${f.score.pnl_points.toFixed(1)}`);
    }
  }
}

main().catch(console.error);
