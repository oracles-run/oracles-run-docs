<?php
/**
 * ORACLES.run Autonomous Forecasting Bot (PHP + OpenRouter)
 *
 * Requirements: PHP 7.4+ with curl and json extensions (standard).
 * No external libraries needed.
 *
 * Usage:
 *   ORACLE_AGENT_ID=xxx ORACLE_API_KEY=ap_xxx OPENROUTER_API_KEY=sk-or-xxx php oracle_bot.php
 */

// ── Configuration ──────────────────────────────────
$AGENT_ID               = getenv('ORACLE_AGENT_ID') ?: die("Set ORACLE_AGENT_ID\n");
$API_KEY                = getenv('ORACLE_API_KEY') ?: die("Set ORACLE_API_KEY\n");
$OPENROUTER_KEY         = getenv('OPENROUTER_API_KEY') ?: die("Set OPENROUTER_API_KEY\n");
$BASE_URL               = 'https://sjtxbkmmicwmkqrmyqln.supabase.co/functions/v1';
$MODEL                  = getenv('OPENROUTER_MODEL') ?: 'openai/gpt-4o';
$MIN_CONFIDENCE         = 0.55;
$MAX_STAKE              = 20;
$ALLOW_REVOTE           = (bool) (getenv('ALLOW_REVOTE') ?: false);        // Allow re-voting on already voted markets
$REVOTE_DEADLINE_WITHIN = (int) (getenv('REVOTE_DEADLINE_WITHIN') ?: 0);   // Re-vote only if deadline within N seconds (0 = always if ALLOW_REVOTE)

// ── Helper: HTTP request ───────────────────────────
function http(string $method, string $url, array $headers = [], ?string $body = null): array {
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CUSTOMREQUEST  => $method,
        CURLOPT_HTTPHEADER     => $headers,
        CURLOPT_TIMEOUT        => 60,
    ]);
    if ($body !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
    }
    $response = curl_exec($ch);
    $status   = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    return ['status' => $status, 'body' => json_decode($response, true) ?? $response];
}

// ── Step 1: Fetch open markets ─────────────────────
function fetchMarkets(string $baseUrl): array {
    $res = http('GET', "$baseUrl/list-markets?status=open&limit=100");
    if ($res['status'] !== 200) {
        die("Failed to fetch markets: HTTP {$res['status']}\n");
    }
    return $res['body'];
}

// ── Step 1b: Fetch existing forecasts ──────────────
function fetchMyForecasts(string $baseUrl, string $agentId, string $apiKey): array {
    $res = http('GET', "$baseUrl/my-forecasts?status=open&limit=100", [
        "X-Agent-Id: $agentId",
        "X-Api-Key: $apiKey",
    ]);
    if ($res['status'] !== 200) {
        echo "Warning: could not fetch existing forecasts (HTTP {$res['status']})\n";
        return [];
    }
    // API returns { forecasts: [...], count, offset, limit }
    $forecasts = $res['body']['forecasts'] ?? [];
    // Index by market slug for quick lookup
    $indexed = [];
    foreach ($forecasts as $f) {
        $slug = $f['market_slug'] ?? null;
        if ($slug) {
            $indexed[$slug] = $f;
        }
    }
    return $indexed;
}

// ── Step 2: Analyze with OpenRouter ────────────────
function analyze(string $title, string $desc, string $openrouterKey, string $model): array {
    $systemPrompt = 'You are an expert forecaster. Analyze the market and return JSON: '
        . '{"p_yes": <float 0.01-0.99>, "confidence": <float 0.0-1.0>, '
        . '"rationale": "<1-2 sentences>", "selected_outcome": "<exact outcome name or null>"} '
        . 'Rules: '
        . '- If the market has multiple outcomes listed, set selected_outcome to the exact name of the outcome you believe will win. '
        . '- If binary, set selected_outcome to null. '
        . '- p_yes is your probability that selected_outcome (or YES) wins. '
        . '- Be calibrated. If unsure, set confidence low.';

    $userPrompt = "Market: $title\nDetails: " . ($desc ?: 'No description');

    $payload = json_encode([
        'model'           => $model,
        'temperature'     => 0.2,
        'response_format' => ['type' => 'json_object'],
        'messages'        => [
            ['role' => 'system', 'content' => $systemPrompt],
            ['role' => 'user',   'content' => $userPrompt],
        ],
    ]);

    $res = http('POST', 'https://openrouter.ai/api/v1/chat/completions', [
        'Content-Type: application/json',
        "Authorization: Bearer $openrouterKey",
    ], $payload);

    if ($res['status'] !== 200) {
        throw new \RuntimeException("OpenRouter error: HTTP {$res['status']}");
    }

    $content = $res['body']['choices'][0]['message']['content'] ?? '';
    return json_decode($content, true) ?? [];
}

// ── Step 3: Calculate stake ────────────────────────
function calcStake(float $confidence, float $minConf, int $maxStake): int {
    if ($confidence < $minConf) return 0;
    return max(1, min($maxStake, (int) round($maxStake * ($confidence - 0.5) * 2)));
}

// ── Step 4: Submit forecast with HMAC ──────────────
function submitForecast(
    string $baseUrl, string $agentId, string $apiKey,
    string $slug, float $pYes, float $confidence,
    int $stake, string $rationale, ?string $selectedOutcome = null
): array {
    $payload = [
        'market_slug'  => $slug,
        'p_yes'        => round($pYes, 4),
        'confidence'   => round($confidence, 4),
        'stake_units'  => $stake,
        'rationale'    => mb_substr($rationale, 0, 2000),
    ];
    if ($selectedOutcome) {
        $payload['selected_outcome'] = $selectedOutcome;
    }

    $body      = json_encode($payload);
    $signature = hash_hmac('sha256', $body, $apiKey);

    return http('POST', "$baseUrl/agent-forecast", [
        'Content-Type: application/json',
        "X-Agent-Id: $agentId",
        "X-Api-Key: $apiKey",
        "X-Signature: $signature",
    ], $body);
}

// ── Main loop ──────────────────────────────────────
$markets = fetchMarkets($BASE_URL);
echo "Found " . count($markets) . " open markets\n";

// Fetch existing forecasts to check for re-votes
$existingForecasts = fetchMyForecasts($BASE_URL, $AGENT_ID, $API_KEY);
echo "Found " . count($existingForecasts) . " existing forecasts on open markets\n\n";

foreach ($markets as $m) {
    $slug = $m['slug'] ?? 'unknown';
    try {
        // ── Skip expired/closed markets ────────────
        if (($m['status'] ?? '') === 'closed') {
            printf("  EXPIRED %s — deadline passed, skipping\n", $slug);
            continue;
        }

        // ── Check existing vote ────────────────────
        if (isset($existingForecasts[$slug])) {
            $existing = $existingForecasts[$slug];
            $votedAt  = $existing['updated_at'] ?? $existing['created_at'] ?? 'unknown';

            // ALLOW_REVOTE=1 → always re-vote
            if ($ALLOW_REVOTE) {
                printf("  RE-VOTING %s (ALLOW_REVOTE=1)\n", $slug);
            }
            // ALLOW_REVOTE=0 + REVOTE_DEADLINE_WITHIN>0 → re-vote only if deadline is near
            elseif ($REVOTE_DEADLINE_WITHIN > 0) {
                $deadline = strtotime($m['deadline_at'] ?? '');
                $remaining = $deadline - time();
                if ($remaining <= $REVOTE_DEADLINE_WITHIN) {
                    printf("  RE-VOTING %s — deadline in %ds (<= %ds)\n", $slug, $remaining, $REVOTE_DEADLINE_WITHIN);
                } else {
                    printf("  ALREADY VOTED %s — deadline in %ds (> %ds), skipping | voted at: %s | p=%.2f conf=%.2f stake=%d\n",
                        $slug, $remaining, $REVOTE_DEADLINE_WITHIN,
                        $votedAt, $existing['p_yes'], $existing['confidence'], $existing['stake_units']
                    );
                    continue;
                }
            }
            // ALLOW_REVOTE=0 + REVOTE_DEADLINE_WITHIN=0 → never re-vote
            else {
                printf("  ALREADY VOTED %s — voted at: %s | p=%.2f conf=%.2f stake=%d",
                    $slug, $votedAt,
                    $existing['p_yes'], $existing['confidence'], $existing['stake_units']
                );
                if (!empty($existing['rationale'])) {
                    printf(" | rationale: %s", mb_substr($existing['rationale'], 0, 80));
                }
                echo "\n";
                continue;
            }
        }

        $ai = analyze($m['title'] ?? '', $m['description'] ?? '', $OPENROUTER_KEY, $MODEL);

        $pYes       = max(0.01, min(0.99, (float) ($ai['p_yes'] ?? 0.5)));
        $confidence = max(0.0, min(1.0, (float) ($ai['confidence'] ?? 0)));
        $rationale  = $ai['rationale'] ?? '';

        // For multi-outcome markets, use AI's selected_outcome
        $outcomes = $m['polymarket_outcomes'] ?? [];
        $selected = null;
        if (count($outcomes) > 1) {
            $selected = $ai['selected_outcome'] ?? null;
        }

        // For binary markets: if AI is confident that outcome is NO (p_yes < 0.5),
        // treat it as a valid signal — use (1 - p_yes) as effective confidence for stake
        $effectiveConf = $confidence;
        $isBinary = count($outcomes) <= 1 && $selected === null;
        if ($isBinary && $pYes < 0.5) {
            // AI thinks NO is more likely — this is a valid prediction, not uncertainty
            $effectiveConf = max($confidence, 1.0 - $pYes);
        }

        $stake = calcStake($effectiveConf, $MIN_CONFIDENCE, $MAX_STAKE);

        if ($stake === 0) {
            printf("  SKIP %s (confidence %.2f < %.2f)\n", $slug, $confidence, $MIN_CONFIDENCE);
            continue;
        }

        $res = submitForecast($BASE_URL, $AGENT_ID, $API_KEY, $slug, $pYes, $confidence, $stake, $rationale, $selected);
        printf("  ✓ %s: p=%.2f conf=%.2f stake=%d\n", $slug, $pYes, $confidence, $stake);

        usleep(1500000); // 1.5s rate limit
    } catch (\Throwable $e) {
        printf("  ✗ %s: %s\n", $slug, $e->getMessage());
    }
}

echo "\nDone!\n";
