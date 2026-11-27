"""Tiny development-only CNN, deterministic JSON weights (never an official checkpoint)."""
import torch
from torch import nn
from .common import SCOPE, read, write


class DemoAutoencoder(nn.Module):
    def __init__(self,channels):
        super().__init__()
        self.network=nn.Sequential(nn.Conv2d(1,channels,3,stride=2,padding=1),nn.ReLU(),
            nn.Conv2d(channels,channels,3,stride=2,padding=1),nn.ReLU(),
            nn.Upsample(scale_factor=2,mode='nearest'),nn.Conv2d(channels,channels,3,padding=1),nn.ReLU(),
            nn.Upsample(scale_factor=2,mode='nearest'),nn.Conv2d(channels,1,3,padding=1),nn.Sigmoid())

    def forward(self,value): return self.network(value)


def seed_everything(seed,threads=1):
    torch.set_num_threads(threads)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    torch.set_float32_matmul_precision('highest')


def save(path,model,channels):
    write(path,{'schema_version':1,'scope':SCOPE,'architecture':'tiny_procedural_ae_v1','channels':channels,
        'state_dict':{key:{'shape':list(value.shape),'values':value.flatten().tolist()} for key,value in sorted(model.state_dict().items())}})


def load(path):
    data=read(path)
    if data['scope']!=SCOPE or data['architecture']!='tiny_procedural_ae_v1': raise ValueError('Not a demo model')
    model=DemoAutoencoder(data['channels'])
    state={key:torch.tensor(value['values'],dtype=torch.float32).reshape(value['shape']) for key,value in data['state_dict'].items()}
    if any(not torch.isfinite(v).all() for v in state.values()): raise ValueError('Invalid model weights')
    model.load_state_dict(state,strict=True)
    return model.eval()


def scores(model,images):
    with torch.inference_mode():
        values=torch.from_numpy(images)
        return ((model(values)-values)**2).mean(dim=(1,2,3)).numpy()
