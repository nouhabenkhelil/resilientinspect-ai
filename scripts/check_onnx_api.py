"""Real HTTP ONNX/PyTorch predictions on a hash-verified permitted val image."""
import base64
import hashlib
import json
from pathlib import Path
import sys
from check_containers import call, multipart

ROOT=Path(__file__).resolve().parents[1]


def main():
    base='http://localhost:18080/api'
    image=ROOT/'data/raw/mvtec_ad/bottle/train/good/002.png'
    content=image.read_bytes()
    assert hashlib.sha256(content).hexdigest()=='7de0414f1744aaf5cec488928ee3b761509e4bad4f607dc4f6d41ad7862dab69'
    report={'checks':{},'predictions':[],'failures':[]}
    health=call(base+'/health');metadata=call(base+'/model/metadata')
    report['checks']['health']=health;report['checks']['metadata']=metadata
    assert health['status']==200 and health['body']['ready_models']==15
    assert len(metadata['body']['models'])==15
    def request(model,engine,path):
        body,headers=multipart(model,'bottle',content)
        boundary=headers['Content-Type'].split('boundary=')[1]
        trailer=f'--{boundary}--\r\n'.encode()
        field=f'--{boundary}\r\nContent-Disposition: form-data; name="engine"\r\n\r\n{engine}\r\n'.encode()
        return call(base+path,body[:-len(trailer)]+field+trailer,headers)
    for model in ('B0','T2'):
        reference=None
        for engine in ('pytorch','onnxruntime'):
            for path in ('/predict','/predict/visualize'):
                result=request(model,engine,path)
                assert result['status']==200,result
                value=result['body'];assert value['engine']==engine
                if reference is None:reference=value
                assert value['threshold']==reference['threshold']
                assert abs(value['anomaly_score']-reference['anomaly_score'])<=1e-5+1e-4*abs(reference['anomaly_score'])
                if value['decision']!=reference['decision']:
                    assert max(abs(value['anomaly_score']-value['threshold']),abs(reference['anomaly_score']-reference['threshold']))<=1e-5
                if path.endswith('/visualize'):
                    visual=value.pop('visualization')
                    assert visual['coordinate_space']=='letterbox_256' and visual['is_segmentation'] is False
                    assert value['explanation_engine']==('pytorch' if model=='T2' else engine)
                    if engine=='onnxruntime' and model=='T2':assert value['explanation_score_coherent'] is True
                    for key in ('image_png_base64','heatmap_png_base64','overlay_png_base64'):
                        assert base64.b64decode(visual.pop(key)).startswith(b'\x89PNG\r\n\x1a\n')
                    value['visualization_metadata']=visual
                report['predictions'].append({'model':model,'engine':engine,'path':path,**result})
                print(model,engine,path,result['status'],flush=True)
    invalid=request('B0','invalid','/predict');assert invalid['status']==422
    report['checks']['invalid_engine']=invalid
    unavailable=next((m for m in metadata['body']['models'] if m['category']=='bottle' and 'onnxruntime' not in m['available_engines']),None)
    if unavailable:
        refused=request(unavailable['model'],'onnxruntime','/predict')
        assert refused['status']==503 and refused['body']['code']=='onnx_unavailable'
        report['checks']['unavailable_engine']=refused
    report['passed']=True
    out=ROOT/'deployment/reports/onnx-http.json';out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(f'Passed: {out}')


if __name__=='__main__':main()
