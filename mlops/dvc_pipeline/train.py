"""Actual CPU gradient training on development normals only."""
import math
import torch
from .common import SCOPE, WORK, execution, finite, integer, load_array, params, sha, write
from .model import DemoAutoencoder, save, seed_everything


def main():
    with execution('training') as receipt:
        config=params('training')
        seed=integer(config['seed'],0,2**31-1); epochs=integer(config['epochs'],1,50)
        batch=integer(config['batch_size'],1,128); channels=integer(config['channels'],2,16)
        threads=integer(config['cpu_threads'],1,2); rate=finite(config['learning_rate'],1e-6,.1)
        seed_everything(seed,threads)
        images=torch.from_numpy(load_array('train.npy'))
        model=DemoAutoencoder(channels).train()
        initial={key:value.detach().clone() for key,value in model.state_dict().items()}
        optimizer=torch.optim.Adam(model.parameters(),lr=rate)
        generator=torch.Generator().manual_seed(seed)
        losses=[]; steps=0
        with torch.no_grad(): initial_loss=float(((model(images)-images)**2).mean())
        for _ in range(epochs):
            order=torch.randperm(len(images),generator=generator)
            total=0.
            for offset in range(0,len(images),batch):
                chunk=images[order[offset:offset+batch]]
                optimizer.zero_grad(set_to_none=True)
                loss=((model(chunk)-chunk)**2).mean()
                if not torch.isfinite(loss): raise ValueError('Nonfinite loss')
                loss.backward(); optimizer.step(); steps+=1
                total+=float(loss.detach())*len(chunk)
            losses.append(total/len(images))
        with torch.no_grad(): final_loss=float(((model(images)-images)**2).mean())
        delta=sum(float(((value-initial[key])**2).sum()) for key,value in model.state_dict().items())
        if not steps or delta<=0 or not math.isfinite(final_loss): raise ValueError('Training did not update model')
        save(WORK/'trained/model.json',model,channels)
        report={'scope':SCOPE,'parameters':config,'architecture':'tiny_procedural_ae_v1','model_sha256':sha(WORK/'trained/model.json'),
            'manifest_sha256':sha(WORK/'prepared/manifest.json'),'initial_loss':initial_loss,'final_loss':final_loss,'epoch_losses':losses,
            'optimizer_steps':steps,'weight_delta_squared':delta,'train_samples':len(images),'selection':'last fixed epoch; no test access'}
        write(WORK/'trained/training.json',report)
        receipt.update(parameters=config,optimizer_steps=steps,model_sha256=report['model_sha256'],final_loss=final_loss)


if __name__=='__main__': main()
