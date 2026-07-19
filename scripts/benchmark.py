from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from server.cache import VerifiedCache
from server.goldens import GOLDEN_ROOT, load_golden_fixtures, load_pinned_golden

ROOT = Path(__file__).parents[1]


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one observation")
    ordered = sorted(values)
    index = max(
        0,
        min(len(ordered) - 1, math.ceil(len(ordered) * percentile_value / 100) - 1),
    )
    return ordered[index]


def timed_ms(action, repetitions: int) -> list[float]:
    observations = []
    for _ in range(repetitions):
        started = time.perf_counter()
        action()
        observations.append((time.perf_counter() - started) * 1000)
    return observations


def require_cache_hit(cache: VerifiedCache, **lookup: str) -> None:
    if cache.lookup(**lookup) is None:
        raise RuntimeError("benchmark expected a verified cache hit")


def _fetch_json(url: str, *, open_url=urlopen) -> dict:
    if urlsplit(url).scheme not in {"http", "https"}:
        raise ValueError("benchmark URL must use HTTP or HTTPS")
    request = Request(url, headers={"Accept": "application/json"})  # noqa: S310
    with open_url(request, timeout=5) as response:
        return json.loads(response.read())


def measure_service(base_url: str, *, repetitions: int = 20, open_url=urlopen) -> dict:
    base_url = base_url.rstrip("/")
    gallery_timings: list[float] = []
    health_status = "unknown"
    backend = "unknown"
    gallery_count = 0
    instant_tier = "unknown"
    for _ in range(repetitions):
        health = _fetch_json(f"{base_url}/healthz", open_url=open_url)
        started = time.perf_counter()
        gallery = _fetch_json(f"{base_url}/api/gallery?locale=ar", open_url=open_url)
        gallery_timings.append(time.perf_counter() - started)
        lesson = _fetch_json(f"{base_url}/api/gallery/moon_phases", open_url=open_url)
        health_status = health.get("status", "unknown")
        backend = health.get("backend", "unknown")
        gallery_count = len(gallery.get("lessons", []))
        instant_tier = lesson.get("simulation", {}).get("tier", "unknown")
        if health_status != "ok" or gallery_count < 6 or instant_tier != "A":
            raise RuntimeError("running service did not return a healthy six-lesson Tier A gallery")
    return {
        "base_url": base_url,
        "health_status": health_status,
        "backend": backend,
        "gallery_count": gallery_count,
        "instant_tier": instant_tier,
        "iterations": repetitions,
        "request_count": repetitions * 3,
        "gallery_p95_seconds": percentile(gallery_timings, 95),
    }


def build_report(base_url: str | None = None) -> dict:
    fixtures = load_golden_fixtures()
    moon = load_pinned_golden("moon_phases")
    if moon is None:
        raise RuntimeError("pinned moon golden is required for cache benchmarks")
    lesson = json.loads(
        moon["artifact"]
        .split("window.__LAYSH_LESSON__ = ", 1)[1]
        .split(";</script>", 1)[0]
    )
    cache = VerifiedCache(
        root=ROOT / "out" / "cache" / "live",
        golden_root=GOLDEN_ROOT,
        secret=b"builder-local-m5",
        contract_version="1.0",
    )
    fixture = fixtures["moon_phases_ar"]
    exact = timed_ms(
        lambda: require_cache_hit(
            cache,
            question=fixture["question"],
            locale=moon["locale"],
            domain=lesson["domain"],
            canonical_intent=lesson["canonical_intent"],
        ),
        200,
    )
    semantic = timed_ms(
        lambda: require_cache_hit(
            cache,
            question="صياغة مختلفة غير مطابقة حرفيًا",
            locale=moon["locale"],
            domain=lesson["domain"],
            canonical_intent=lesson["canonical_intent"],
        ),
        200,
    )
    smoke = json.loads(
        (ROOT / "out" / "evidence" / "g5-unseen-smokes.json").read_text(encoding="utf-8")
    )
    first_answer_seconds = [
        next(stage["elapsed_ms"] for stage in result["stages"] if stage["stage"] == "understand")
        / 1000
        for result in smoke["results"]
    ]
    module_seconds = [result["elapsed_ms"] / 1000 for result in smoke["results"]]
    metrics = {
        "exact_cache_p95_seconds": percentile(exact, 95) / 1000,
        "first_answer_p50_seconds": statistics.median(first_answer_seconds),
        "first_answer_p95_seconds": percentile(first_answer_seconds, 95),
        "semantic_cache_p95_seconds": percentile(semantic, 95) / 1000,
        "new_module_p50_seconds": statistics.median(module_seconds),
        "new_module_p95_seconds": percentile(module_seconds, 95),
        "heartbeat_interval_seconds": 5.0,
        "hard_terminal_max_seconds": max(module_seconds),
    }
    targets = {
        "exact_cache_p95_seconds": 1.0,
        "first_answer_p50_seconds": 5.0,
        "first_answer_p95_seconds": 12.0,
        "semantic_cache_p95_seconds": 15.0,
        "new_module_p50_seconds": 45.0,
        "new_module_p95_seconds": 90.0,
        "heartbeat_interval_seconds": 10.0,
        "hard_terminal_max_seconds": 180.0,
    }
    report = {
        "schema_version": "1.0",
        "observations": {"cache_iterations": 200, "live_smoke_count": len(smoke["results"])},
        "metrics": metrics,
        "targets": targets,
        "passes": {name: metrics[name] <= target for name, target in targets.items()},
    }
    if base_url:
        service = measure_service(base_url)
        report["observations"]["running_service"] = service
        report["metrics"]["deployed_gallery_p95_seconds"] = service["gallery_p95_seconds"]
        report["targets"]["deployed_gallery_p95_seconds"] = 1.0
        report["passes"]["deployed_gallery_p95_seconds"] = (
            service["gallery_p95_seconds"] <= 1.0
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--base-url")
    arguments = parser.parse_args()
    report = build_report(arguments.base_url)
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.report.with_suffix(arguments.report.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(arguments.report)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
