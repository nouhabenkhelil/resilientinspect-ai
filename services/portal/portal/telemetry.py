"""Safe JSON logs and bounded-cardinality, measured HTTP telemetry."""
from collections import deque
from datetime import datetime, timezone
import hmac
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
import time
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

SAFE_FIELDS = {'request_id', 'correlation_id', 'batch_id', 'task_id', 'upstream_request_id', 'route', 'method',
               'status', 'duration_ms', 'slot', 'outcome', 'action', 'error_code', 'attempt', 'service'}


class JsonFormatter(logging.Formatter):
    def format(self, record):
        # Never interpolate arbitrary log messages/arguments or exception text.
        event = getattr(record, 'event', None)
        if not isinstance(event, str) or not re.fullmatch(r'[a-zA-Z0-9_.]{1,80}', event):
            event = record.name if re.fullmatch(r'[a-zA-Z0-9_.]{1,80}', record.name) else 'application'
        result = {'at': datetime.now(timezone.utc).isoformat(), 'level': record.levelname, 'event': event}
        for field in SAFE_FIELDS:
            value = getattr(record, field, None)
            if value is not None: result[field] = str(value)[:160] if not isinstance(value, (int, float, bool)) else value
        if record.exc_info: result['error_type'] = record.exc_info[0].__name__
        return json.dumps(result, ensure_ascii=True, allow_nan=False)


def configure_logging(service):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):
        log = logging.getLogger(name); log.handlers[:] = []; log.propagate = True
    for name in ('httpx', 'httpx2', 'httpcore', 'httpcore2', 'authlib', 'sqlalchemy.engine'):
        logging.getLogger(name).setLevel(logging.WARNING)


def emit(event, **fields):
    logging.getLogger('portal.operations').info(event, extra={'event': event, **fields})


def metric_token():
    try: value = Path(os.environ.get('METRICS_TOKEN_FILE', '/run/secrets/metrics_token')).read_text().strip()
    except OSError: return ''
    return value if len(value) >= 43 else ''


def service_authorized(request):
    expected = metric_token()
    return bool(expected) and hmac.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + expected)


class HTTPMetrics:
    def __init__(self):
        self.registry = CollectorRegistry()
        self.count = Counter('ri_http_requests_total', 'Completed gateway HTTP requests', ['route', 'method', 'status_class'], registry=self.registry)
        self.latency = Histogram('ri_http_request_duration_seconds', 'Gateway duration in seconds', ['route', 'method'],
            buckets=(.005, .01, .025, .05, .1, .25, .5, 1, 2, 5, 10, 30, 60, 120), registry=self.registry)
        self.samples = deque(maxlen=4096)
        self.started = time.monotonic()

    def observe(self, scope, status, duration):
        route = getattr(scope.get('route'), 'path', '/unmatched')
        method = scope.get('method', '')
        if method not in {'GET', 'POST', 'PATCH', 'PUT', 'DELETE', 'OPTIONS', 'HEAD'}: method = 'OTHER'
        if route == '/metrics': return
        self.count.labels(route, method, f'{status // 100}xx').inc()
        self.latency.labels(route, method).observe(duration)
        self.samples.append((time.monotonic(), status, duration))
        state = scope.get('state', {})
        emit('http.completed', service='portal', request_id=state.get('request_id'), correlation_id=state.get('correlation_id'),
             route=route, method=method, status=status, duration_ms=round(duration * 1000, 3))

    def summary(self):
        rows = [r for r in self.samples if time.monotonic() - r[0] <= 300]
        latency = sorted(r[2] for r in rows)
        return {'window_seconds': min(300, round(time.monotonic() - self.started, 2)), 'sample_limit': 4096,
                'requests': len(rows), 'errors_5xx': sum(r[1] >= 500 for r in rows),
                'error_ratio': sum(r[1] >= 500 for r in rows) / len(rows) if rows else None,
                'mean_ms': sum(latency) * 1000 / len(latency) if rows else None,
                'p95_ms': latency[math.ceil(.95 * len(latency)) - 1] * 1000 if rows else None}

    def render(self): return generate_latest(self.registry)
