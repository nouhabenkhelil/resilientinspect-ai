"""Authenticated optional science proxy + read-only SQL exporter, isolated from science."""
from collections import deque
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
import psycopg
from psycopg.rows import dict_row
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from .core import CONFIG, DATA, SECRETS, KEYS, Store, grouped

REGISTRY = CollectorRegistry()
HTTP = Counter('ri_mon_http_requests_total', 'Optional science proxy requests, not direct bypass traffic', ['route','method','status_class'], registry=REGISTRY)
LATENCY = Histogram('ri_mon_http_request_duration_seconds', 'End-to-end optional proxy duration', ['route','method'],
    buckets=(.005,.01,.025,.05,.1,.25,.5,1,2,5,10,30,60,120), registry=REGISTRY)
SAMPLES = deque(maxlen=10000)
STATE = {'sql_up': 0, 'last_collection': 0, 'invalid_rows': 0, 'truncated': 0}
STORE = None
ALLOWED = {}


def collect_sql():
    url = (SECRETS / 'database_url').read_text().strip()
    with psycopg.connect(url, connect_timeout=3, options='-c statement_timeout=3000 -c default_transaction_read_only=on', row_factory=dict_row) as db:
        rows = db.execute("SELECT * FROM mlops_monitoring.prediction_metadata WHERE timestamp >= extract(epoch FROM now()) - %s ORDER BY timestamp DESC LIMIT 10001", (CONFIG['retention_days'] * 86400,)).fetchall()
    STATE['truncated'] = int(len(rows) > 10000)
    cutoff = json.loads((DATA / 'activation.json').read_text())['activated_at']
    for item in rows[:10000]:
        item = dict(item)
        item['timestamp'] = float(item['timestamp'])
        item['source'] = 'historical' if item['timestamp'] < cutoff else 'production'
        try:
            if tuple(item[k] for k in KEYS[:-1]) not in ALLOWED: raise ValueError('unknown release')
            STORE.add(item)
        except (ValueError, TypeError): STATE['invalid_rows'] += 1
    STORE.prune()
    STATE.update(sql_up=1, last_collection=time.time())


def loop():
    while True:
        try: collect_sql()
        except Exception: STATE['sql_up'] = 0
        time.sleep(CONFIG['collect_seconds'])


def render():
    registry = CollectorRegistry()
    def gauge(name, help, value, labels=None):
        if value is None: return
        labels = labels or {}
        metric = metrics.get(name)
        if metric is None:
            metric = metrics[name] = Gauge(name, help, list(labels), registry=registry)
        (metric.labels(**labels) if labels else metric).set(value)
    metrics = {}
    now = time.time()
    gauge('ri_mon_sql_up', 'Privacy-view collection success', STATE['sql_up'])
    gauge('ri_mon_collection_age_seconds', 'Age of last successful metadata collection', now - STATE['last_collection'] if STATE['last_collection'] else None)
    gauge('ri_mon_invalid_rows', 'Rejected rows encountered since collector start (not unique)', STATE['invalid_rows'])
    gauge('ri_mon_collection_truncated', 'SQL collection hit 10000-row cap; increase capacity before interpreting', STATE['truncated'])
    gauge('ri_mon_scrape_probe_up', 'Collector self probe; Prometheus up is authoritative', 1, {'source':'production'})
    try:
        with urllib.request.urlopen(os.getenv('SCIENTIFIC_URL','http://science:8000')+'/health', timeout=3) as response: health = json.load(response)
        gauge('ri_mon_service_up', 'Real science health probe', 1, {'source':'production'})
        for engine, count in health['ready_models_by_engine'].items():
            if engine in ('pytorch','onnxruntime'): gauge('ri_mon_models_ready', 'Real admitted model count', count, {'engine':engine,'source':'production'})
    except Exception: gauge('ri_mon_service_up', 'Real science health probe', 0, {'source':'production'})
    samples = [s for s in list(SAMPLES) if now-s[0] <= 300]
    gauge('ri_mon_api_window_requests', 'Actual optional proxy requests in five minutes (bounded at 10000)', len(samples), {'source':'production'})
    if samples:
        gauge('ri_mon_api_error_ratio', 'Actual optional proxy 5xx ratio in five minutes', sum(s[1]>=500 for s in samples)/len(samples), {'source':'production'})
        if len(samples) >= 40:
            gauge('ri_mon_api_p95_seconds', 'Nearest rank p95; >=40 actual optional proxy requests', sorted(s[2] for s in samples)[__import__('math').ceil(.95*len(samples))-1], {'source':'production'})
    try:
        host = json.loads((DATA / 'host.json').read_text())
        gauge('ri_mon_host_collection_up','Host observation file available and valid',1)
        gauge('ri_mon_host_collection_age_seconds','Age of Windows host and Docker CLI observations',now-host['measured_at'])
        if now-host['measured_at'] <= CONFIG['freshness_seconds']:
            for field in ('cpu_ratio','memory_ratio','memory_used_bytes','memory_total_bytes'):
                gauge('ri_mon_host_'+field, 'Measured Windows host '+field, host[field], {'source':'production'})
            for item in host['containers']:
                for field in ('up','cpu_ratio','memory_bytes','memory_limit_bytes'):
                    if field in item: gauge('ri_mon_container_'+field,'Measured Docker container '+field,item[field], {'container':item['container'],'source':'production'})
    except (OSError, ValueError, KeyError):
        gauge('ri_mon_host_collection_up','Host observation file available and valid',0)
    groups = grouped(STORE.rows())
    for key, rows in groups.items():
        labels = dict(zip(KEYS, key)); n = len(rows)
        gauge('ri_mon_prediction_window_count', 'Predictions retained in configured window, not a lifetime counter', n, labels)
        gauge('ri_mon_score_window_mean', 'Actual mean score in window', sum(r['anomaly_score'] for r in rows)/n, labels)
        gauge('ri_mon_anomaly_window_ratio', 'Actual decisions anomaly in window', sum(r['decision']=='anomaly' for r in rows)/n, labels)
        gauge('ri_mon_inference_window_mean_seconds', 'Actual recorded scientific inference duration mean', sum(r['inference_time_ms'] for r in rows)/n/1000, labels)
        for edge in (.05,.1,.2,.3,.4,.5,.6,.7,.8,.9,1,float('inf')):
            gauge('ri_mon_score_window_bucket', 'Cumulative score histogram over configured window; use without rate()',sum(r['anomaly_score'] <= edge for r in rows),{**labels,'le':str(edge) if edge!=float('inf') else '+Inf'})
    try:
        drift = json.loads((DATA / 'drift.json').read_text())
        gauge('ri_mon_drift_report_up','Drift aggregate report available and valid',1)
        gauge('ri_mon_drift_age_seconds', 'Age of last successful drift computation', now-drift['measured_at'])
        for group in drift['groups']:
            labels = {k:group[k] for k in KEYS}
            gauge('ri_mon_drift_evaluable','Enough valid samples and matching reference',int(group['status'] in ('stable','drift') and now-drift['measured_at'] <= CONFIG['freshness_seconds']),labels)
            if now-drift['measured_at'] <= CONFIG['freshness_seconds']:
                for field in ('ks_distance','anomaly_rate_delta'):
                    gauge('ri_mon_drift_'+field,'Empirical validation-to-window '+field,group.get(field),labels)
    except (OSError, ValueError, KeyError): gauge('ri_mon_drift_report_up','Drift aggregate report available and valid',0)
    # Safe local fixture series use the same alert expressions, always labeled synthetic.
    try: demo = json.loads((DATA / 'demo.json').read_text())
    except (OSError, ValueError): demo = {}
    if now < demo.get('expires_at',0) <= now+180:
        for metric,value in {'service_up':0,'scrape_probe_up':0,'api_error_ratio':1,'api_p95_seconds':15,
                             'host_cpu_ratio':1,'host_memory_ratio':1,'models_ready':0,'control_age_seconds':999}.items():
            labels={'source':'synthetic'}
            if metric=='models_ready': labels['engine']='pytorch'
            gauge('ri_mon_'+metric,'Isolated expiring alert demonstration fixture',value,labels)
    gauge('ri_mon_control_age_seconds','Age of actual metadata collection', max(now-STATE['last_collection'], 0) if STATE['last_collection'] else None, {'source':'production'})
    return generate_latest(REGISTRY) + generate_latest(registry)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # no URL, filenames, multipart or token logging

    def reply(self, status, content, kind='application/json'):
        self.send_response(status); self.send_header('Content-Type',kind); self.send_header('Content-Length',str(len(content))); self.end_headers()
        self.wfile.write(content)

    def authorized(self):
        expected = 'Bearer ' + (SECRETS / 'metrics_token').read_text().strip()
        return hmac.compare_digest(self.headers.get('Authorization',''), expected)

    def do_GET(self):
        if self.path == '/health': return self.reply(200,b'{"status":"ok"}')
        if not self.authorized(): return self.reply(401,b'{"code":"authentication_required"}')
        if self.path == '/metrics':
            try: content=render()
            except Exception: return self.reply(503,b'{"code":"monitoring_collection_failed"}')
            return self.reply(200,content,'text/plain; version=0.0.4')
        if self.path in ('/science/health','/science/model/metadata'): return self.proxy()
        return self.reply(404,b'{}')

    def do_POST(self):
        if not self.authorized(): return self.reply(401,b'{"code":"authentication_required"}')
        if self.path not in ('/science/predict','/science/predict/visualize'): return self.reply(404,b'{}')
        self.proxy()

    def proxy(self):
        start=time.monotonic(); status=502; route=self.path.removeprefix('/science')
        try:
            source = self.headers.get('X-Monitor-Source','production')
            if source not in ('production','validation','synthetic'): return self.reply(400,b'{"code":"invalid_source"}')
            length=int(self.headers.get('Content-Length','0'))
            if length < 0 or length > 11*1024*1024: return self.reply(413,b'{"code":"body_too_large"}')
            if self.headers.get('Transfer-Encoding'): return self.reply(400,b'{"code":"content_length_required"}')
            body=self.rfile.read(length) if self.command=='POST' else None
            request=urllib.request.Request(os.getenv('SCIENTIFIC_URL','http://science:8000')+route,data=body,method=self.command,
                headers={'Content-Type':self.headers.get('Content-Type','application/octet-stream')})
            try: response=urllib.request.urlopen(request,timeout=120)
            except urllib.error.HTTPError as error: response=error
            with response:
                status=response.status; content=response.read(32*1024*1024); kind=response.headers.get('Content-Type','application/json')
            if status==200 and self.command=='POST':
                try:
                    row=json.loads(content)
                    row.update(identity=row.pop('request_id'),source=source,timestamp=time.time())
                    if tuple(row[k] for k in KEYS[:-1]) not in ALLOWED: raise ValueError('unknown release')
                    STORE.add(row)
                except (ValueError, TypeError, KeyError): STATE['invalid_rows']+=1
            self.reply(status,content,kind)
        except Exception:
            status=502; self.reply(status,b'{"code":"upstream_unavailable"}')
        finally:
            elapsed=time.monotonic()-start
            HTTP.labels(route,self.command,str(status//100)+'xx').inc(); LATENCY.labels(route,self.command).observe(elapsed)
            SAMPLES.append((time.time(),status,elapsed))


def main():
    global STORE, ALLOWED
    STORE=Store()
    reference=json.loads((DATA/'reference.json').read_text())
    if hashlib.sha256((DATA/'reference.json').read_bytes()).hexdigest() != (DATA/'reference.sha256').read_text().strip(): raise ValueError('reference checksum')
    ALLOWED={tuple(g[k] for k in KEYS[:-1]):g for g in reference['groups']}
    threading.Thread(target=loop,daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0',9108),Handler).serve_forever()


if __name__=='__main__': main()
