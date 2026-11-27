"""Reproducible dashboards provisioned through the existing Grafana authenticated API."""
def definitions():
    dashboards=[]
    def add(key,title,description,panels,variables=False):
        values=[]
        for index,(label,expr,unit) in enumerate(panels):
            defaults={'unit':unit}
            if unit=='percentunit' and 'per core' not in label: defaults.update(min=0,max=1)
            legend='{{job}} {{route}} {{method}} {{engine}} {{container}} {{status_class}}'
            if variables: legend='{{model}} / {{category}} / {{engine}} / {{source}} / {{version}}'+(' / le={{le}}' if 'bucket' in expr else '')
            if expr.startswith('ALERTS'): legend='{{alertname}} / {{source}}'
            values.append({'id':index+1,'title':label,'type':'timeseries','datasource':{'type':'prometheus','uid':'ri-prom'},
                'gridPos':{'x':index%2*12,'y':index//2*8,'w':12,'h':8},
                'fieldConfig':{'defaults':defaults,'overrides':[]},
                'targets':[{'refId':'A','expr':expr,'legendFormat':legend}]})
        dashboards.append({'uid':'ri-mlops-'+key,'title':'MLOps · '+title,'schemaVersion':41,'version':1,'editable':True,
            'tags':['resilientinspect','mlops'],'description':description,'refresh':'10s','time':{'from':'now-30m','to':'now'},
            'templating':{'list':[{'name':'source','type':'custom','query':'production,validation,synthetic,historical','current':{'text':'production','value':'production'}}] if variables else []},
            'panels':values})
    add('infrastructure','Infrastructure','Windows CPU/RAM via psutil; container CPU: one core = 100%. Stale host samples disappear; freshness remains visible.',[
        ('Windows CPU','ri_mon_host_cpu_ratio{source="production"}','percentunit'),
        ('Windows RAM','ri_mon_host_memory_ratio{source="production"}','percentunit'),
        ('Container memory','ri_mon_container_memory_bytes{source="production"}','bytes'),
        ('Container CPU (per core)','ri_mon_container_cpu_ratio{source="production"}','percentunit'),
        ('Container running','ri_mon_container_up{source="production"}','short'),
        ('Science availability','ri_mon_service_up{source="production"}','short'),
        ('Host collection age','ri_mon_host_collection_age_seconds','s'),
        ('Monitoring alerts (source visible)','ALERTS{alertname=~"MLOps.*",alertstate="firing"}','short')])
    api_panels=[('HTTP requests per second (portal + optional science proxy)','sum by (job,route,method) (rate({__name__=~"ri_http_requests_total|ri_mon_http_requests_total"}[5m]))','reqps'),
        ('Science proxy status classes','sum by (route,status_class) (increase(ri_mon_http_requests_total[5m]))','short'),
        ('Portal status classes','sum by (route,status_class) (increase(ri_http_requests_total[5m]))','short'),
        ('Mean duration (optional proxy)','sum by (route) (rate(ri_mon_http_request_duration_seconds_sum[5m])) / sum by (route) (rate(ri_mon_http_request_duration_seconds_count[5m]))','s'),
        ('5xx ratio (optional proxy)','ri_mon_api_error_ratio{source="production"}','percentunit'),
        ('Ready models (real health)','ri_mon_models_ready{source="production"}','short')]
    for quantile,minimum in [(.5,20),(.95,40),(.99,100)]:
        api_panels.append((f'Proxy p{round(quantile*100)} (minimum {minimum} observations/5m)',f'histogram_quantile({quantile}, sum by (route,le) (rate(ri_mon_http_request_duration_seconds_bucket[5m]))) and on(route) (sum by(route) (increase(ri_mon_http_request_duration_seconds_count[5m])) >= {minimum})','s'))
    add('api','API Performance','Portal metrics cover portal traffic. Optional proxy metrics cover /science/* calls only; direct internal science requests bypass the proxy. Quantiles require sufficient observations; empty is not zero.',api_panels)
    select='{source="$source"}'
    add('models','Model Monitoring','24-hour metadata window, 7-day retention. Every series separates release SHA, model, category, engine and origin. No accuracy/AUROC/F1 or image feature drift without measurements/labels. Reference is frozen normal validation.',[
        ('Prediction observations in window','ri_mon_prediction_window_count'+select,'short'),
        ('Mean anomaly score','ri_mon_score_window_mean'+select,'short'),
        ('Anomaly decision ratio','ri_mon_anomaly_window_ratio'+select,'percentunit'),
        ('Scientific inference mean','ri_mon_inference_window_mean_seconds'+select,'s'),
        ('Score distribution (cumulative bins)','ri_mon_score_window_bucket'+select,'short'),
        ('KS distance (only enough data)','ri_mon_drift_ks_distance'+select,'short'),
        ('Absolute anomaly-rate shift','ri_mon_drift_anomaly_rate_delta'+select,'percentunit'),
        ('Drift evaluable (0 = insufficient/missing/invalid)','ri_mon_drift_evaluable'+select,'short'),
        ('Drift computation age','ri_mon_drift_age_seconds','s'),
        ('Metadata SQL collector up','ri_mon_sql_up','short')],True)
    return dashboards
