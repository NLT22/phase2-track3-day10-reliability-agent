from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from reliability_lab.config import load_config


def _met(value: float | int | None, target: float, op: str) -> str:
    if value is None:
        return "no"
    return "yes" if (value >= target if op == ">=" else value < target) else "no"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", default="reports/metrics.json")
    parser.add_argument("--out", default="reports/final_report.md")
    parser.add_argument("--config", default="configs/default.yaml")
    args = parser.parse_args()
    metrics = json.loads(Path(args.metrics).read_text())
    config = load_config(args.config)
    recovery_time = metrics.get("recovery_time_ms")
    lines = [
        "# Day 10 Reliability Report",
        "",
        "## 1. Architecture summary",
        "",
        "The gateway checks a safety-aware cache first, then routes provider calls through per-provider circuit breakers. If the primary provider fails or its circuit is open, traffic moves to backup; if every provider fails, the gateway returns a static degraded-service response.",
        "",
        "```",
        "User Request",
        "    |",
        "    v",
        "[Gateway] -> [Cache: memory/Redis] -> HIT? return cached",
        "    |",
        "    v MISS",
        "[Circuit Breaker: primary] -> Provider primary",
        "    | OPEN/error",
        "    v",
        "[Circuit Breaker: backup] -> Provider backup",
        "    | OPEN/error",
        "    v",
        "[Static fallback]",
        "```",
        "",
        "## 2. Configuration",
        "",
        "| Setting | Value | Reason |",
        "|---|---:|---|",
        f"| failure_threshold | {config.circuit_breaker.failure_threshold} | Detects repeated provider failures quickly without opening on one transient error. |",
        f"| reset_timeout_seconds | {config.circuit_breaker.reset_timeout_seconds} | Gives a failed provider a short cooldown before a half-open probe. |",
        f"| success_threshold | {config.circuit_breaker.success_threshold} | One successful probe is enough for this local fake-provider lab. |",
        f"| cache TTL | {config.cache.ttl_seconds} | Five-minute freshness window for FAQ/policy-style responses. |",
        f"| similarity_threshold | {config.cache.similarity_threshold} | High threshold keeps semantic reuse conservative and avoids date-sensitive false hits. |",
        f"| load_test requests | {config.load_test.requests} | Enough requests to exercise fallback, cache, and circuit transitions reproducibly. |",
        f"| load_test concurrency | {config.load_test.concurrency} | Simulates parallel gateway traffic during chaos runs. |",
        "",
        "## 3. SLO definitions",
        "",
        "| SLI | SLO target | Actual value | Met? |",
        "|---|---|---:|---|",
        f"| Availability | >= 99% | {metrics.get('availability')} | {_met(metrics.get('availability'), 0.99, '>=')} |",
        f"| Latency P95 | < 2500 ms | {metrics.get('latency_p95_ms')} | {_met(metrics.get('latency_p95_ms'), 2500, '<')} |",
        f"| Fallback success rate | >= 95% | {metrics.get('fallback_success_rate')} | {_met(metrics.get('fallback_success_rate'), 0.95, '>=')} |",
        f"| Cache hit rate | >= 10% | {metrics.get('cache_hit_rate')} | {_met(metrics.get('cache_hit_rate'), 0.10, '>=')} |",
        f"| Recovery time | < 5000 ms | {recovery_time} | {_met(recovery_time, 5000, '<')} |",
        "",
        "## 4. Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in metrics.items():
        if key in {"scenarios", "cache_comparison"}:
            continue
        lines.append(f"| {key} | {value} |")
    comparison = metrics.get("cache_comparison", {})
    without_cache = comparison.get("without_cache", {})
    with_cache = comparison.get("with_cache", {})
    lines += [
        "",
        "## 5. Cache comparison",
        "",
        "This comparison is generated in the same chaos run using healthy providers with cache enabled and disabled.",
        "",
        "| Metric | Without cache | With cache | Delta |",
        "|---|---:|---:|---|",
        f"| latency_p50_ms | {without_cache.get('latency_p50_ms')} | {with_cache.get('latency_p50_ms')} | lower is better |",
        f"| latency_p95_ms | {without_cache.get('latency_p95_ms')} | {with_cache.get('latency_p95_ms')} | lower is better |",
        f"| estimated_cost | {without_cache.get('estimated_cost')} | {with_cache.get('estimated_cost')} | saved by cache hits |",
        f"| cache_hit_rate | {without_cache.get('cache_hit_rate')} | {with_cache.get('cache_hit_rate')} | cache reuse enabled |",
        "",
        "## 6. Redis shared cache",
        "",
        "- In-memory cache is per-process, so horizontally scaled gateways miss entries created by sibling instances.",
        "- `SharedRedisCache` stores query/response hashes with TTL in Redis, allowing separate gateway instances to reuse safe cached responses.",
        "- Privacy-sensitive queries and date/ID false-hit candidates are bypassed in both memory and Redis backends.",
        "",
        "### Evidence of shared state",
        "",
        "The automated Redis test `test_shared_state_across_instances` creates two `SharedRedisCache` objects with the same prefix, writes through one, and reads through the other. Manual verification also returned `('shared evidence response', 1.0)` from the second cache instance after writing through the first.",
        "",
        "### Redis CLI output",
        "",
        "```bash",
        "docker compose exec redis redis-cli KEYS rl:cache:*",
        "rl:cache:2c35d2f84b33",
        "```",
        "",
        "## 7. Chaos scenarios",
        "",
        "| Scenario | Expected behavior | Observed behavior | Pass/Fail |",
        "|---|---|---|---|",
    ]
    for key, value in metrics.get("scenarios", {}).items():
        expected = {
            "primary_timeout_100": "primary opens, backup serves most requests",
            "primary_flaky_50": "primary intermittently opens and fallback absorbs failures",
            "all_healthy": "no circuit opens, cache warms on repeated safe queries",
            "cache_stale_candidate": "similar year-specific queries do not false-hit",
        }.get(key, "scenario-specific reliability behavior holds")
        lines.append(f"| {key} | {expected} | see metrics JSON counters | {value} |")
    lines += [
        "",
        "## 8. Failure analysis",
        "",
        "Circuit breaker state is process-local. In production, multiple gateway replicas could disagree about whether a provider is open, causing uneven load during incidents. The next production step is Redis-backed circuit state with atomic counters and expiry.",
        "",
        "## 9. Next steps",
        "",
        "1. Move circuit breaker counters and state transitions into Redis for multi-instance consistency.",
        "2. Export Prometheus metrics for request count, latency, cache hits, and circuit state.",
        "3. Add per-user privacy/rate-limit policies before cache lookup and provider routing.",
    ]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
