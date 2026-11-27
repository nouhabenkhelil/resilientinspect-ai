"""Calibrate a demo-only threshold on independent normals, evaluate held-out synthetic labels."""
import numpy as np
from .common import SCOPE, WORK, execution, finite, load_array, params, read, sha, write
from .model import load, scores, seed_everything


def metrics(labels,values,threshold):
    if not np.isfinite(values).all() or set(labels.tolist())!={0,1}: raise ValueError('Invalid held-out evaluation')
    predictions=values>threshold
    tp=int(((labels==1)&predictions).sum()); tn=int(((labels==0)&~predictions).sum())
    fp=int(((labels==0)&predictions).sum()); fn=int(((labels==1)&~predictions).sum())
    positive,negative=values[labels==1],values[labels==0]
    auc=float(((positive[:,None]>negative[None,:]).sum()+.5*(positive[:,None]==negative[None,:]).sum())/(len(positive)*len(negative)))
    return {'demo_accuracy':(tp+tn)/len(labels),'demo_auroc':auc,'demo_f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.,
            'true_positive':tp,'true_negative':tn,'false_positive':fp,'false_negative':fn,'test_samples':len(labels),
            'demo_threshold':float(threshold)}


def main():
    with execution('evaluation') as receipt:
        config=params('evaluation'); quantile=finite(config['normal_quantile'],.5,.999)
        seed_everything(0,1)
        training=read(WORK/'trained/training.json')
        if sha(WORK/'trained/model.json')!=training['model_sha256']: raise ValueError('Model checksum mismatch')
        model=load(WORK/'trained/model.json')
        calibration=scores(model,load_array('calibration.npy'))
        # Threshold fixed before scoring the held-out test; never optimize it on test labels.
        threshold=float(np.quantile(calibration,quantile,method='linear'))
        values=scores(model,load_array('test.npy')); labels=load_array('test_labels.npy')
        result=metrics(labels,values,threshold)
        if not all(np.isfinite(v) for v in result.values()): raise ValueError('Invalid evaluation metric')
        write(WORK/'evaluation/metrics.json',result)
        write(WORK/'evaluation/report.json',{'scope':SCOPE,'official_scientific_metrics':False,'parameters':config,
            'model_sha256':training['model_sha256'],'manifest_sha256':sha(WORK/'prepared/manifest.json'),
            'threshold_source':'independent procedural calibration normals only','calibration_samples':len(calibration),
            'test_source':'independent procedural test seed; known synthetic labels','metrics':result,
            'predictions':[{'sample_id':f'test-{i:04d}','label':int(label),'score':float(score),'decision':int(score>threshold)} for i,(label,score) in enumerate(zip(labels,values))]})
        receipt.update(parameters=config,model_sha256=training['model_sha256'],metrics=result)


if __name__=='__main__': main()
