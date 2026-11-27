"""Generate/prepare independent procedural splits; no official dataset access."""
import hashlib
import numpy as np
from .common import MODULE, SCOPE, WORK, execution, integer, params, read, sha, write


def generate(count, size, seed, anomalies=0):
    rng = np.random.default_rng(seed)
    grid = np.arange(size,dtype=np.float64)[None,:]
    images=[]
    for index in range(count):
        phase=rng.uniform(-.2,.2)
        stripe=np.sin(grid/size*4*np.pi+phase)
        values=.35+.10*stripe+rng.normal(0,.012,(size,size))
        if index >= count-anomalies:
            width=size//4
            y,x=rng.integers(0,size-width+1,size=2)
            values[y:y+width,x:x+width]=.95
        image=np.rint(np.clip(values,0,1)*255).astype(np.uint8)
        images.append(image)
    return np.stack(images)[:,None,:,:].astype(np.float32)/np.float32(255)


def main():
    with execution('preprocessing') as receipt:
        config=params('data'); recipe=read(MODULE/'recipe.json')
        seed=integer(config['seed'],0,2**31-2000001); size=integer(config['image_size'],16,64)
        if size%4: raise ValueError('Image size must be divisible by four')
        counts={k:integer(config[k],8,2048) for k in ('train_samples','calibration_samples','test_normal_samples','test_anomaly_samples')}
        arrays={
            'train.npy':generate(counts['train_samples'],size,seed+recipe['split_seed_offsets']['train']),
            'calibration.npy':generate(counts['calibration_samples'],size,seed+recipe['split_seed_offsets']['calibration']),
            'test.npy':generate(counts['test_normal_samples']+counts['test_anomaly_samples'],size,seed+recipe['split_seed_offsets']['test'],counts['test_anomaly_samples']),
            'test_labels.npy':np.array([0]*counts['test_normal_samples']+[1]*counts['test_anomaly_samples'],dtype=np.uint8)}
        directory=WORK/'prepared'
        # Validate the fixed output directory before writing any array.
        write(directory/'quality.json',{'scope':SCOPE,'status':'preparing'})
        entries=[]; seen=set()
        for filename,values in arrays.items():
            if not np.isfinite(values).all() or values.min()<0 or values.max()>1: raise ValueError('Invalid generated range')
            if filename!='test_labels.npy':
                split=filename.removesuffix('.npy')
                for index,image in enumerate(values):
                    digest=hashlib.sha256(image.tobytes()).hexdigest()
                    if digest in seen: raise ValueError('Duplicate content across samples or splits')
                    seen.add(digest)
                    entries.append({'sample_id':f'{split}-{index:04d}','split':split,'label':int(arrays['test_labels.npy'][index]) if split=='test' else 0,'sha256':digest})
            path=directory/filename
            if path.is_symlink(): raise ValueError('Linked array output refused')
            np.save(path,values,allow_pickle=False)
        quality={'scope':SCOPE,'sample_count':len(entries),'unique_content_count':len(seen),'splits':{k:len(arrays[k+'.npy']) for k in ('train','calibration','test')},
                 'no_cross_split_duplicates':True,'finite_pixels':True,'range':[0,1],'train_and_calibration_normal_only':True,
                 'held_out_test_has_both_labels':True,'external_data_used':False}
        write(directory/'manifest.json',{'scope':SCOPE,'data_parameters':config,'recipe_sha256':sha(MODULE/'recipe.json'),
            'files':{name:sha(directory/name) for name in arrays},'samples':entries})
        write(directory/'quality.json',quality)
        receipt.update(parameters=config,manifest_sha256=sha(directory/'manifest.json'),samples=len(entries))


if __name__=='__main__': main()
