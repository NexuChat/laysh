import json

from scripts.benchmark import measure_service, percentile


def test_benchmark_percentile_uses_nearest_rank_without_hiding_tail_latency():
    assert percentile([1, 2], 50) == 1
    assert percentile([1, 2], 95) == 2
    assert percentile([4, 1, 3, 2], 95) == 4


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def test_service_benchmark_measures_health_and_instant_gallery_without_model_calls():
    requests: list[str] = []

    def open_url(request, timeout):
        assert timeout == 5
        requests.append(request.full_url)
        if request.full_url.endswith("/healthz"):
            return _Response({"status": "ok", "backend": "codex"})
        if request.full_url.endswith("/api/gallery?locale=ar"):
            return _Response({"lessons": [{"id": str(index)} for index in range(6)]})
        return _Response({"simulation": {"tier": "A", "elapsed_ms": 0}})

    result = measure_service(
        "http://127.0.0.1:8765",
        repetitions=2,
        open_url=open_url,
    )

    assert result["health_status"] == "ok"
    assert result["backend"] == "codex"
    assert result["gallery_count"] == 6
    assert result["instant_tier"] == "A"
    assert result["request_count"] == 6
    assert result["gallery_p95_seconds"] >= 0
    assert requests.count("http://127.0.0.1:8765/healthz") == 2
    assert requests.count("http://127.0.0.1:8765/api/gallery?locale=ar") == 2
    assert requests.count("http://127.0.0.1:8765/api/gallery/moon_phases") == 2
