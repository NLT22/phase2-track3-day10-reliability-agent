# Day 10 Reliability Report

## 1. Architecture summary

The gateway checks a safety-aware cache first, then routes provider calls through per-provider circuit breakers. If the primary provider fails or its circuit is open, traffic moves to backup; if every provider fails, the gateway returns a static degraded-service response.

```
User Request
    |
    v
[Gateway] -> [Cache: memory/Redis] -> HIT? return cached
    |
    v MISS
[Circuit Breaker: primary] -> Provider primary
    | OPEN/error
    v
[Circuit Breaker: backup] -> Provider backup
    | OPEN/error
    v
[Static fallback]
```

## 2. Configuration

| Setting | Value | Reason |
|---|---:|---|
| failure_threshold | 3 | Detects repeated provider failures quickly without opening on one transient error. |
| reset_timeout_seconds | 2.0 | Gives a failed provider a short cooldown before a half-open probe. |
| success_threshold | 1 | One successful probe is enough for this local fake-provider lab. |
| cache TTL | 300 | Five-minute freshness window for FAQ/policy-style responses. |
| similarity_threshold | 0.92 | High threshold keeps semantic reuse conservative and avoids date-sensitive false hits. |
| load_test requests | 100 | Enough requests to exercise fallback, cache, and circuit transitions reproducibly. |
| load_test concurrency | 10 | Simulates parallel gateway traffic during chaos runs. |

## 3. SLO definitions

| SLI | SLO target | Actual value | Met? |
|---|---|---:|---|
| Availability | >= 99% | 1.0 | yes |
| Latency P95 | < 2500 ms | 494.21 | yes |
| Fallback success rate | >= 95% | 1.0 | yes |
| Cache hit rate | >= 10% | 0.691 | yes |
| Recovery time | < 5000 ms | 3079.2752504348755 | yes |

## 4. Metrics

| Metric | Value |
|---|---:|
| total_requests | 301 |
| availability | 1.0 |
| error_rate | 0.0 |
| latency_p50_ms | 0.28 |
| latency_p95_ms | 494.21 |
| latency_p99_ms | 541.57 |
| fallback_success_rate | 1.0 |
| cache_hit_rate | 0.691 |
| circuit_open_count | 2 |
| recovery_time_ms | 3079.2752504348755 |
| estimated_cost | 0.041974 |
| estimated_cost_saved | 0.208 |

## 5. Cache comparison

This comparison is generated in the same chaos run using healthy providers with cache enabled and disabled.

| Metric | Without cache | With cache | Delta |
|---|---:|---:|---|
| latency_p50_ms | 217.1 | 1.05 | lower is better |
| latency_p95_ms | 246.47 | 238.65 | lower is better |
| estimated_cost | 0.05892 | 0.01917 | saved by cache hits |
| cache_hit_rate | 0.0 | 0.66 | cache reuse enabled |

## 6. Redis shared cache

- In-memory cache is per-process, so horizontally scaled gateways miss entries created by sibling instances.
- `SharedRedisCache` stores query/response hashes with TTL in Redis, allowing separate gateway instances to reuse safe cached responses.
- Privacy-sensitive queries and date/ID false-hit candidates are bypassed in both memory and Redis backends.

### Evidence of shared state

The automated Redis test `test_shared_state_across_instances` creates two `SharedRedisCache` objects with the same prefix, writes through one, and reads through the other. Manual verification also returned `('shared evidence response', 1.0)` from the second cache instance after writing through the first.

### Redis CLI output

```bash
docker compose exec redis redis-cli KEYS rl:cache:*
rl:cache:2c35d2f84b33
```

## 7. Chaos scenarios

| Scenario | Expected behavior | Observed behavior | Pass/Fail |
|---|---|---|---|
| primary_timeout_100 | primary opens, backup serves most requests | see metrics JSON counters | pass |
| primary_flaky_50 | primary intermittently opens and fallback absorbs failures | see metrics JSON counters | pass |
| all_healthy | no circuit opens, cache warms on repeated safe queries | see metrics JSON counters | pass |
| cache_stale_candidate | similar year-specific queries do not false-hit | see metrics JSON counters | pass |

## 8. Failure analysis

Circuit breaker state is process-local. In production, multiple gateway replicas could disagree about whether a provider is open, causing uneven load during incidents. The next production step is Redis-backed circuit state with atomic counters and expiry.

## 9. Next steps

1. Move circuit breaker counters and state transitions into Redis for multi-instance consistency.
2. Export Prometheus metrics for request count, latency, cache hits, and circuit state.
3. Add per-user privacy/rate-limit policies before cache lookup and provider routing.