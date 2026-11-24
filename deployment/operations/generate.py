"""Generate configurable alert rules and six dashboards; no fabricated time series."""
import json
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
DEFAULTS = {'unavailable_for': '30s', 'worker_for': '30s', 'queue_age_seconds': 180, 'queue_for': '60s',
            'failed_recent': 3, 'latency_seconds': 5, 'latency_for': '120s', 'min_storage_bytes': 268435456}


def main():
    path = HERE / 'thresholds.yml'
    if not path.exists(): path.write_text(yaml.safe_dump(DEFAULTS))
    c = yaml.safe_load(path.read_text())
    rules = []
    def alert(name, expr, hold, summary): rules.append({'alert': name, 'expr': expr, 'for': hold, 'labels': {'severity': 'warning'}, 'annotations': {'summary': summary}})
    alert('ScientificBackendUnavailable', 'ri_science_up == 0', c['unavailable_for'], 'Le backend scientifique ne répond pas au healthcheck')
    alert('GatewayUnavailable', 'ri_gateway_up == 0 or up{job="portal"} == 0', c['unavailable_for'], 'Gateway indisponible')
    alert('WorkerInactive', 'ri_worker_up == 0', c['worker_for'], 'Heartbeat worker absent ou trop ancien')
    alert('BatchQueueStalled', f'ri_batch_pending > 0 and ri_batch_oldest_pending_seconds > {c["queue_age_seconds"]}', c['queue_for'], 'File batch bloquée')
    alert('RepeatedTaskFailures', f'ri_batch_failed_recent >= {c["failed_recent"]}', c['unavailable_for'], 'Échecs répétés des tâches sur les quinze dernières minutes')
    alert('HighGatewayLatency', f'histogram_quantile(0.95, sum by (le) (rate(ri_http_request_duration_seconds_bucket[5m]))) > {c["latency_seconds"]}', c['latency_for'], 'Latence p95 élevée sur les requêtes mesurées')
    alert('PostgreSQLUnavailable', 'ri_database_up == 0', c['unavailable_for'], 'PostgreSQL ne répond pas à SELECT 1')
    alert('PrivateStorageLow', f'ri_storage_free_bytes < {c["min_storage_bytes"]}', c['unavailable_for'], 'Espace disponible faible dans le filesystem du volume privé Docker')
    (HERE / 'alerts.yml').write_text(yaml.safe_dump({'groups': [{'name': 'resilientinspect', 'rules': rules}]}, sort_keys=False))
    dashboards = [
        ('health', '01 · Santé globale', [('Services disponibles', '{__name__=~"ri_(gateway|science|database|worker)_up"}', 'none'), ('Cibles Prometheus', 'up', 'none')]),
        ('api', '02 · Requêtes API', [('Débit HTTP mesuré', 'sum by (route) (rate(ri_http_requests_total[5m]))', 'reqps'), ('Ratio 5xx', 'sum(rate(ri_http_requests_total{status_class="5xx"}[5m])) / sum(rate(ri_http_requests_total[5m]))', 'percentunit'), ('Latence p95', 'histogram_quantile(0.95,sum by (le)(rate(ri_http_request_duration_seconds_bucket[5m])))', 's')]),
        ('batches', '03 · Surveillance des lots', [('Images en attente', 'ri_batch_pending', 'short'), ('Images en cours', 'ri_batch_running', 'short'), ('Âge de la file', 'ri_batch_oldest_pending_seconds', 's')]),
        ('processing', '04 · Traitements et erreurs', [('Durée moyenne moteur', 'ri_batch_mean_inference_ms', 'ms'), ('Retries conservés', 'ri_batch_retries', 'short'), ('Échecs récents', 'ri_batch_failed_recent', 'short'), ('Défaillances worker enregistrées', 'ri_worker_failures', 'short')]),
        ('database', '05 · PostgreSQL et stockage', [('Disponibilité SQL', 'ri_database_up', 'none'), ('Temps SELECT 1', 'ri_database_probe_seconds', 's'), ('Espace libre filesystem privé', 'ri_storage_free_bytes', 'bytes')]),
        ('engines', '06 · Moteurs scientifiques', [('Disponibilité backend', 'ri_science_up', 'none'), ('Modèles admis par moteur', 'ri_models_available', 'short')]),
    ]
    directory = HERE / 'dashboards'; directory.mkdir(exist_ok=True)
    for key, title, definitions in dashboards:
        panels = [{'id': i+1, 'title': label, 'type': 'timeseries', 'datasource': {'type': 'prometheus', 'uid': 'ri-prom'},
                   'gridPos': {'h': 9, 'w': 12, 'x': (i % 2)*12, 'y': (i//2)*9},
                   'targets': [{'refId': 'A', 'expr': expr, 'legendFormat': '{{__name__}} {{engine}} {{route}}'}],
                   'fieldConfig': {'defaults': {'unit': unit}, 'overrides': []}, 'options': {'tooltip': {'mode': 'multi'}}}
                  for i, (label, expr, unit) in enumerate(definitions)]
        (directory / (key+'.json')).write_text(json.dumps({'uid': 'ri-'+key, 'title': title, 'schemaVersion': 39,
            'version': 1, 'editable': False, 'timezone': 'browser', 'refresh': '10s', 'time': {'from': 'now-30m', 'to': 'now'},
            'tags': ['resilientinspect', 'real-measurements'], 'panels': panels}, indent=2))
    print('Eight alert rules and six real-query dashboards generated. Thresholds are operational starting values.')


if __name__ == '__main__': main()
