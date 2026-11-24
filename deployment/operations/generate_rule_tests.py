"""Synthetic alert fixtures: distinct from the real isolated outage tests."""
from pathlib import Path
import yaml
HERE=Path(__file__).resolve().parent
rules=yaml.safe_load((HERE/'alerts.yml').read_text())['groups'][0]['rules']
series=[]
for name,bad,good in [('ri_science_up',0,1),('ri_gateway_up',0,1),('ri_worker_up',0,1),
 ('ri_batch_pending',2,0),('ri_batch_oldest_pending_seconds',200,0),('ri_batch_failed_recent',3,0),
 ('ri_database_up',0,1),('ri_storage_free_bytes',1,999999999)]:
    series.append({'series':name,'values':f'{bad}+0x30 {good}+0x70'})
for le in ['1','5','10','+Inf']:
    series.append({'series':'ri_http_request_duration_seconds_bucket{le="'+le+'"}',
                   'values':'0+0x30 10+10x70' if le in ['1','5'] else '0+10x101'})
checks=[]
for rule in rules:
    checks.extend([{'eval_time':'3m','alertname':rule['alert'],'exp_alerts':[{'exp_labels':{'severity':'warning'},'exp_annotations':rule['annotations']}]},
                   {'eval_time':'15m','alertname':rule['alert'],'exp_alerts':[]}])
(HERE/'rule-tests.yml').write_text(yaml.safe_dump({'rule_files':['/rules/alerts.yml'],'evaluation_interval':'10s',
  'tests':[{'interval':'10s','input_series':series,'alert_rule_test':checks}]},sort_keys=False))
