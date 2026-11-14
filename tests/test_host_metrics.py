"""REQ-INFRA-0025: latency percentiles, disk, memory, CPU and the database pool in /metrics."""
import asyncio

from app import host_metrics


def test_quantiles_of_request_durations():
    assert host_metrics.quantiles([]) == {}
    q = host_metrics.quantiles([i / 100 for i in range(1, 101)])
    assert q[0.5] == 0.51 and q[0.95] == 0.96 and q[0.99] == 1.0


def test_middleware_records_each_http_request():
    async def app(scope, receive, send):
        await asyncio.sleep(0)

    before = len(host_metrics.SAMPLES)
    wrapped = host_metrics.LatencyMiddleware(app)
    asyncio.run(wrapped({"type": "http"}, None, None))
    asyncio.run(wrapped({"type": "lifespan"}, None, None))          # not an HTTP request: not counted
    assert len(host_metrics.SAMPLES) == min(before + 1, host_metrics.SAMPLES.maxlen)


def test_lines_are_prometheus_gauges(tmp_path):
    host_metrics.SAMPLES.extend([0.01, 0.02, 0.5])
    text = host_metrics.lines(str(tmp_path))
    for name in ("vpnshop_http_request_seconds{quantile=\"0.95\"}", "vpnshop_disk_free_bytes{mount=\"root\"}",
                 "vpnshop_disk_free_bytes{mount=\"media\"}", "vpnshop_cpu_count", "# TYPE vpnshop_disk_total_bytes gauge"):
        assert name in text, name
    for line in text.splitlines():
        assert line.startswith("#") or line.split()[-1].replace(".", "", 1).replace("e-", "", 1).isdigit(), line


def test_the_app_measures_latency():
    from app.main import app
    assert any(m.cls is host_metrics.LatencyMiddleware for m in app.user_middleware)
