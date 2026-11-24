"""Generate private observability/backup configuration without printing secrets."""
import json
import os
from pathlib import Path
import secrets
import bcrypt
import yaml

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / 'deployment/industrial/local/observability'


def main():
    LOCAL.mkdir(parents=True, exist_ok=True)
    private = LOCAL / 'secrets'; private.mkdir(exist_ok=True)
    def secret(name):
        path = private / name
        if not path.exists(): path.write_text(secrets.token_urlsafe(36))
        return path.read_text().strip()
    token, prom_password, grafana_password, observer_password = [secret(n) for n in ('metrics_token', 'prometheus_password', 'grafana_password', 'observer_password')]
    (private / 'grafana_username').write_text('ri-admin')
    (private / 'observer_database_url').write_text(f'postgresql+psycopg://ri_observer:{observer_password}@postgres:5432/portal')
    (LOCAL / 'prometheus-web.yml').write_text(yaml.safe_dump({'basic_auth_users': {'ri-operator': bcrypt.hashpw(prom_password.encode(), bcrypt.gensalt()).decode()}}))
    (LOCAL / 'datasource.yml').write_text(yaml.safe_dump({'apiVersion': 1, 'datasources': [{'name': 'ResilientInspect', 'uid': 'ri-prom',
        'type': 'prometheus', 'url': 'http://prometheus:9090', 'access': 'proxy', 'isDefault': True, 'basicAuth': True,
        'basicAuthUser': 'ri-operator', 'secureJsonData': {'basicAuthPassword': prom_password}}]}))
    (LOCAL / '.env').write_text('GRAFANA_ADMIN_USER=ri-admin\n')
    backup_root = Path.home() / 'ResilientInspectBackups'
    key_root = Path.home() / '.resilientinspect-secrets'
    backup_root.mkdir(exist_ok=True); key_root.mkdir(exist_ok=True)
    key_path = key_root / 'backup.key'
    if not key_path.exists(): key_path.write_bytes(secrets.token_bytes(32))
    config = {'backup_root': str(backup_root), 'key_file': str(key_path), 'core_interval_hours': 24, 'mlops_interval_days': 7,
              'keep_core': 7, 'keep_mlops': 4, 'dvc_root': str(Path.home() / 'resilientinspect-dvc-store'),
              'mlflow_root': str(ROOT / 'mlops/local/mlflow')}
    path = LOCAL / 'backup-config.json'
    if not path.exists(): path.write_text(json.dumps(config, indent=2))
    print('Private configuration generated; values withheld. Backups outside the repository; separate encryption key file.')


if __name__ == '__main__': main()
