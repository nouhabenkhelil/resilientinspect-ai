"""Sanitize actual benchmark/parity measurements for frontend and scientific report."""
import argparse
import json
from pathlib import Path
import csv
import shutil

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark',type=Path,required=True)
    parser.add_argument('--hardware',required=True)
    args=parser.parse_args()
    benchmark=json.loads(args.benchmark.read_text(encoding='utf-8'))
    raw_output=ROOT/'reports/experiments/onnx'
    raw_output.mkdir(parents=True,exist_ok=True)
    shutil.copy2(args.benchmark,raw_output/'benchmark.json')
    shutil.copy2(args.benchmark.with_suffix('.csv'),raw_output/'benchmark.csv')
    shutil.copy2(ROOT/'deployment/reports/portability/onnx-linux/parity.json',raw_output/'parity.json')
    rows=[]
    for row in benchmark['models']:
        graph=ROOT/'artifacts/onnx'/row['model']/row['category']
        parity=json.loads((graph/'parity-linux.json').read_text())
        sizes=row['sizes']
        rows.append({'model':row['model'],'category':row['category'],'parity':parity['status'],
                     'normal_examples':parity['normal_examples'],'synthetic_examples':parity['synthetic_examples'],
                     'decision_changes':parity['decision_changes'],'max_score_error':parity['max_score_error'],
                     'score':row['conditions']['score'], 'forward':row['conditions']['forward'],
                     'sizes':{'checkpoint':sizes['checkpoint_training_bytes'],'weights':sizes['inference_state_dict_bytes'],'onnx':sizes['graph_bytes']}})
    public={'status':'measured','environment':benchmark['environment'],'hardware':args.hardware,'models':rows}
    (ROOT/'frontend/src/data/onnx-performance.json').write_text(json.dumps(public,indent=2)+'\n',encoding='utf-8')
    output=ROOT/'reports/experiments/onnx_benchmark.md'
    lines=['# ONNX Runtime — mesures CPU FP32','',args.hardware,'',
           'Deux threads, batch 1, 20 warm-ups puis 100 mesures par moteur et condition. Ordre des moteurs alterné ; mêmes images val. Aucune image test, aucun seuil ajusté.',
           '', '| Modele | PT p50 score ms | ORT p50 score ms | PT p95 ms | ORT p95 ms | PT/ORT moyenne | Parite |', '| --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for r in rows:
        s=r['score'];lines.append(f"| {r['model']}/{r['category']} | {s['pytorch']['p50_ms']:.3f} | {s['onnxruntime']['p50_ms']:.3f} | {s['pytorch']['p95_ms']:.3f} | {s['onnxruntime']['p95_ms']:.3f} | {s['speedup_mean']:.3f} | {r['parity']} |")
    lines+=['','## Statistiques par condition','',
            '| Modele | Condition | Moteur | Moyenne ms | p50 ms | p95 ms | Ecart-type ms | Images/s |',
            '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for row in benchmark['models']:
        for condition in ('forward','score'):
            for engine in ('pytorch','onnxruntime'):
                m=row['conditions'][condition][engine]
                lines.append(f"| {row['model']}/{row['category']} | {condition} | {engine} | {m['mean_ms']:.3f} | {m['p50_ms']:.3f} | {m['p95_ms']:.3f} | {m['std_ms']:.3f} | {m['images_per_second']:.2f} |")
    lines+=['','Benchmark limité aux deux familles pilotes B0 et T2, chacune sur les trois catégories. A1/T0/T1 ne sont pas chronométrés : aucune accélération ne leur est attribuée.',
            '', '## Chargement, mémoire et explication', '',
            '| Modele | Chargement PT avec integrite ms | Session ORT ms | RSS processus Mo | Grad-CAM PT p50 ms | Grad-CAM PT p95 ms |',
            '| --- | ---: | ---: | ---: | ---: | ---: |']
    for r in benchmark['models']:
        cam=r.get('gradcam')
        p50=f"{cam['p50_ms']:.3f}" if cam else 'Sans objet'
        p95=f"{cam['p95_ms']:.3f}" if cam else 'Sans objet'
        lines.append(f"| {r['model']}/{r['category']} | {r['pytorch_load_with_integrity_ms']:.3f} | {r['onnx_session_load_ms']:.3f} | {r['rss_process_both_engines_bytes']/1e6:.2f} | {p50} | {p95} |")
    lines+=['','Les frontières de chargement diffèrent explicitement : PyTorch inclut les contrôles scientifiques et SHA ; ORT mesure la création/optimisation de session après admission. Aucun facteur de chargement n’est calculé.',
            '', '## Artefacts et mesures brutes', '',
            '[benchmark.csv](onnx/benchmark.csv) · [benchmark.json](onnx/benchmark.json) · [parity.json](onnx/parity.json) · [politique préalable](../../deployment/ONNX_PROTOCOL.md).',
            '', '| Modele | Checkpoint entrainement Mo | Poids inference Mo | Graphe ONNX Mo |', '| --- | ---: | ---: | ---: |']
    for r in rows:
        s=r['sizes'];lines.append(f"| {r['model']}/{r['category']} | {s['checkpoint']/1e6:.3f} | {s['weights']/1e6:.3f} | {s['onnx']/1e6:.3f} |")
    lines+=['','## Portee et limites','',
            'Score = normalisation commune + forward + calcul scientifique du score ; décodage/letterbox et HTTP exclus. Le forward seul est mesuré séparément dans benchmark.json et benchmark.csv. Les mesures Grad-CAM PyTorch sont séparées et ne servent jamais au facteur ONNX.',
            'La mémoire RSS est un instantané du processus avec les deux réseaux présents, pas une mesure attribuable à un moteur. La taille du checkpoint peut inclure l’optimiseur ; state_dict et ONNX sont des tailles d’inférence séparées.',
            'Machine partagée avec des services de fond ; aucun autre benchmark, test navigateur ou mesure intensive lancé par l’agent pendant ces mesures. Résultats locaux non assimilables à un benchmark de production isolé.',
            'Les exports refusés sont listés dans les preuves de parité, sans tolérances élargies. Les nombres affichés dans React viennent exclusivement de ce benchmark.',
            '', '## Preuves de parite par modele', '', '| Modele | Exemples | Statut | Ecart score maximal | Changements de decision | Injustifies |', '| --- | ---: | --- | ---: | ---: | ---: |']
    for path in sorted((ROOT/'artifacts/onnx').glob('*/*/parity-linux.json')):
        r=json.loads(path.read_text());lines.append(f"| {r['model']}/{r['category']} | {len(r['rows'])} | {r['status']} | {r['max_score_error']:.9g} | {r['decision_changes']} | {r['unjustified_changes']} |")
    lines+=['','## Environnement effectif','', '```json',json.dumps(benchmark['environment'],indent=2),'```']
    lines+=['','## Export refuse : T1/bottle','',
            'Sous Windows et Linux, le même normal de validation bottle/train/good/201.png et sa recette synthétique normale produisent un écart de score hors politique. Aucun changement de décision, mais cela ne suffit pas à admettre le graphe. Les autres recettes ne sont pas utilisées pour recalibrer ou élargir les tolérances. Le moteur PyTorch reste disponible.',
            'Les tenseurs logits passent leur tolérance distincte, mais le score sigmoid dépasse sa propre limite : c’est une incompatibilité numérique mesurée entre les kernels FP32, pas une autorisation de changer les seuils. La cause algorithmique exacte de l’écart entre kernels n’est pas isolée ici.',
            '', '![Latences score p50](onnx_latency.png)', '', '![Débit séquentiel](onnx_throughput.png)']
    output.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    selected=[r for r in rows if r['category']=='bottle']
    fig,ax=plt.subplots(figsize=(8,4));x=list(range(len(selected)));width=.36
    ax.bar([i-width/2 for i in x],[r['score']['pytorch']['p50_ms'] for r in selected],width,label='PyTorch')
    ax.bar([i+width/2 for i in x],[r['score']['onnxruntime']['p50_ms'] for r in selected],width,label='ONNX Runtime')
    ax.set_xticks(x,[r['model'] for r in selected]);ax.set_ylabel('Score complet p50 (ms)');ax.set_title('CPU FP32 — bottle — batch 1, deux threads');ax.legend();fig.tight_layout()
    fig.savefig(ROOT/'reports/experiments/onnx_latency.png',dpi=180);plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,4))
    ax.bar([i-width/2 for i in x],[r['score']['pytorch']['images_per_second'] for r in selected],width,label='PyTorch')
    ax.bar([i+width/2 for i in x],[r['score']['onnxruntime']['images_per_second'] for r in selected],width,label='ONNX Runtime')
    ax.set_xticks(x,[r['model'] for r in selected]);ax.set_ylabel('Images / seconde (séquentiel)');ax.set_title('CPU FP32 — bottle — score complet');ax.legend();fig.tight_layout()
    fig.savefig(ROOT/'reports/experiments/onnx_throughput.png',dpi=180);plt.close(fig)
    print(f'Published {len(rows)} measured benchmark rows to frontend and {output.name}')


if __name__=='__main__': main()
