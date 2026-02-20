<?php
/**
 * ORACLES.run V2 Autonomous Forecasting Bot (PHP + OpenRouter)
 *
 * Uses the V2 Packs API: fetches round tasks → analyzes with AI → submits batch predictions.
 * No 0.7× scoring penalty (unlike legacy v1 API).
 *
 * Requirements: PHP 7.4+ with curl and json extensions (standard).
 * No external libraries needed.
 *
 * Usage:
 *   ORACLE_AGENT_ID=xxx ORACLE_API_KEY=ap_xxx OPENROUTER_API_KEY=sk-or-xxx php oracle_bot_v2.php
 */

// ── Configuration ──────────────────────────────────
$AGENT_ID       = getenv('ORACLE_AGENT_ID') ?: die("Set ORACLE_AGENT_ID\n");
$API_KEY        = getenv('ORACLE_API_KEY') ?: die("Set ORACLE_API_KEY\n");
$OPENROUTER_KEY = getenv('OPENROUTER_API_KEY') ?: die("Set OPENROUTER_API_KEY\n");
$BASE_URL       = 'https://sjtxbkmmicwmkqrmyqln.supabase.co/functions/v1';
$MODEL          = getenv('OPENROUTER_MODEL') ?: 'openai/gpt-4o';
$PACK_SLUG      = getenv('ORACLE_PACK') ?: '';       // Optional: filter by pack slug (e.g. 'btc-daily')
$CUSTOMER_SLUG  = getenv('ORACLE_CUSTOMER') ?: '';    // Optional: filter by customer slug
$MIN_CONFIDENCE = 0.55;
$MAX_STAKE      = 20;
$BATCH_SIZE     = 50;  // Max predictions per batch (API limit)

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

// ── Step 1: Fetch round tasks ──────────────────────
function fetchTasks(string $baseUrl, string $packSlug, string $customerSlug): array {
    $params = [];
    if ($packSlug)     $params[] = "pack=$packSlug";
    if ($customerSlug) $params[] = "customer=$customerSlug";
    $qs  = $params ? '?' . implode('&', $params) : '';
    $res = http('GET', "$baseUrl/agent-tasks$qs");

    if ($res['status'] !== 200) {
        die("Failed to fetch tasks: HTTP {$res['status']}\n");
    }
    return $res['body'];
}

// ── Step 2: Analyze a single task with OpenRouter ──
function analyzeTask(string $question, string $category, ?string $resolutionRule, string $openrouterKey, string $model): array {
    $systemPrompt = 'You are an expert forecaster. Analyze the question and return JSON: '
        . '{"p_yes": <float 0.01-0.99>, "confidence": <float 0.0-1.0>, '
        . '"rationale": "<1-2 sentences>"} '
        . 'Rules: '
        . '- p_yes is your probability that the answer is YES. '
        . '- Be calibrated. If unsure, set confidence low.';

    $details = "Category: $category";
    if ($resolutionRule) {
        $details .= "\nResolution rule: $resolutionRule";
    }

    $payload = json_encode([
        'model'           => $model,
        'temperature'     => 0.2,
        'response_format' => ['type' => 'json_object'],
        'messages'        => [
            ['role' => 'system', 'content' => $systemPrompt],
            ['role' => 'user',   'content' => "Question: $question\n$details"],
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

// ── Step 4: Submit batch predictions with HMAC ─────
function submitBatch(
    string $baseUrl, string $agentId, string $apiKey,
    string $roundId, array $predictions
): array {
    $payload = [
        'round_id'    => $roundId,
        'predictions' => $predictions,
    ];

    $body      = json_encode($payload);
    $signature = hash_hmac('sha256', $body, $apiKey);

    return http('POST', "$baseUrl/agent-predictions-batch", [
        'Content-Type: application/json',
        "X-Agent-Id: $agentId",
        "X-Api-Key: $apiKey",
        "X-Signature: $signature",
    ], $body);
}

// ── Main ───────────────────────────────────────────
echo "🔮 ORACLES.run V2 Bot (PHP + OpenRouter)\n";
echo "Model: $MODEL\n";
if ($PACK_SLUG)     echo "Pack filter: $PACK_SLUG\n";
if ($CUSTOMER_SLUG) echo "Customer filter: $CUSTOMER_SLUG\n";
echo "\n";

// Step 1: Fetch current round and tasks
$data = fetchTasks($BASE_URL, $PACK_SLUG, $CUSTOMER_SLUG);

$round = $data['round'] ?? null;
$tasks = $data['tasks'] ?? [];
$rules = $data['rules'] ?? [];

if (!$round) {
    echo "No open round found.\n";
    exit(0);
}

$minConf = $rules['min_confidence'] ?? $MIN_CONFIDENCE;

printf("Round: %s (ends: %s)\n", $round['id'], $round['ends_at'] ?? '?');
printf("Tasks: %d | Min confidence: %.2f\n\n", count($tasks), $minConf);

if (count($tasks) === 0) {
    echo "No tasks in this round.\n";
    exit(0);
}

// Step 2: Analyze each task
$predictions = [];
$skipped     = 0;
$errors      = 0;

foreach ($tasks as $task) {
    $question     = $task['question'] ?? 'Unknown';
    $category     = $task['category'] ?? '';
    $packMarketId = $task['pack_market_id'] ?? null;
    $resolution   = $task['resolution_rule'] ?? null;

    if (!$packMarketId) {
        echo "  ⚠ Skipping task without pack_market_id\n";
        $errors++;
        continue;
    }

    try {
        $ai = analyzeTask($question, $category, $resolution, $OPENROUTER_KEY, $MODEL);

        $pYes       = max(0.01, min(0.99, (float) ($ai['p_yes'] ?? 0.5)));
        $confidence = max(0.0, min(1.0, (float) ($ai['confidence'] ?? 0)));
        $rationale  = $ai['rationale'] ?? '';

        // Binary strategy: if AI thinks NO (p_yes < 0.5), boost effective confidence
        $effectiveConf = $confidence;
        if ($pYes < 0.5) {
            $effectiveConf = max($confidence, 1.0 - $pYes);
        }

        $stake = calcStake($effectiveConf, $minConf, $MAX_STAKE);

        if ($stake === 0) {
            printf("  SKIP %-50s conf=%.2f < %.2f\n", mb_substr($question, 0, 50), $confidence, $minConf);
            $skipped++;
            continue;
        }

        $predictions[] = [
            'pack_market_id' => $packMarketId,
            'p_yes'          => round($pYes, 4),
            'confidence'     => round($confidence, 4),
            'stake'          => $stake,
            'rationale_500'  => mb_substr($rationale, 0, 500),
        ];

        printf("  ✓ %-50s p=%.2f conf=%.2f stake=%d\n",
            mb_substr($question, 0, 50), $pYes, $confidence, $stake);

        usleep(1000000); // 1s rate limit for OpenRouter
    } catch (\Throwable $e) {
        printf("  ✗ %-50s %s\n", mb_substr($question, 0, 50), $e->getMessage());
        $errors++;
    }
}

echo "\n";

// Step 3: Submit batch
if (count($predictions) === 0) {
    echo "No predictions to submit.\n";
    exit(0);
}

// Split into batches of BATCH_SIZE
$batches = array_chunk($predictions, $BATCH_SIZE);
$totalUpserted = 0;
$totalErrors   = 0;

foreach ($batches as $i => $batch) {
    printf("Submitting batch %d/%d (%d predictions)...\n", $i + 1, count($batches), count($batch));

    $res = submitBatch($BASE_URL, $AGENT_ID, $API_KEY, $round['id'], $batch);

    if ($res['status'] === 200 && ($res['body']['ok'] ?? false)) {
        $upserted = $res['body']['upserted'] ?? 0;
        $batchErrors = $res['body']['errors'] ?? [];
        $totalUpserted += $upserted;
        $totalErrors += count($batchErrors);

        printf("  ✓ Upserted: %d", $upserted);
        if (count($batchErrors) > 0) {
            printf(" | Errors: %d", count($batchErrors));
            foreach ($batchErrors as $err) {
                printf("\n    - %s: %s", $err['pack_market_id'] ?? '?', $err['error'] ?? '?');
            }
        }
        echo "\n";
    } else {
        $error = $res['body']['error'] ?? "HTTP {$res['status']}";
        printf("  ✗ Batch failed: %s\n", $error);
        $totalErrors += count($batch);
    }
}

// Summary
echo "\n";
echo "═══════════════════════════════════════\n";
printf("Round:     %s\n", $round['id']);
printf("Analyzed:  %d tasks\n", count($tasks));
printf("Submitted: %d predictions\n", $totalUpserted);
printf("Skipped:   %d (low confidence)\n", $skipped);
printf("Errors:    %d\n", $errors + $totalErrors);
echo "═══════════════════════════════════════\n";
echo "Done!\n";
