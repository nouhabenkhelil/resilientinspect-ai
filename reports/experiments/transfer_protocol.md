# Phase 3 Transfer Learning T0 T1 T2

Date : 9 novembre 2026. Étape limitée à l'implémentation, aux tests synthétiques
et aux smoke CPU. Aucun entraînement complet ni test officiel lancé.

Le guide `resilientinspect-ai/guide_technique.docx.docx` a été lu, notamment
§4.3, §5.3 et son tableau T0/T1/T2, §5.5 et §5.6. Son SHA256 est
`e859160de14566fe8d67c9d37d089d2c8cb74a1573867e61bdc9f70c53d4142f`.
Les choix B0/A1, leurs données, configurations et résultats restent inchangés.
La tâche de classification synthétique est auxiliaire ; elle ne remplace pas
la reconstruction AE et ne garantit aucun gain sur les défauts industriels.

## Architecture et conditions comparées

Backbone `torchvision.models.efficientnet_b0`, pool global, tête commune
`Dropout(p=0.2) → Linear(1280,1)`. Sortie : un logit par image ; apprentissage
par `BCEWithLogitsLoss`, score continu `sigmoid(logit)` pour anomalie=1.
La tête est initialisée séparément avec la seed commune, sans dépendre de la
consommation RNG du constructeur du backbone. Elle est donc identique au début
des trois conditions pour une même seed.

| Variante | Initialisation | Stages entraînés | Paramètres entraînables | LR tête | LR backbone |
| --- | --- | --- | ---: | ---: | ---: |
| T0 | Aléatoire | `features[0:9]` et tête | 4 008 829 | 0,001 | 0,001 |
| T1 | ImageNet V1 | Tête seulement | 1 281 | 0,001 | Aucun |
| T2 | Même ImageNet V1 | `features[6]`, `[7]`, `[8]` et tête | 3 157 021 | 0,001 | 0,0001 |

Chaque modèle comporte 4 008 829 paramètres au total. En T2, le backbone
entraînable compte 3 155 740 paramètres ; les 851 808 autres sont gelés.
Les stages 6/7 sont les derniers groupes MBConv, et 8 la projection terminale.
Les BatchNorm des stages gelés restent en mode eval, avec leurs buffers
inchangés ; leur stochastic depth est aussi désactivé. Les stages entraînés
utilisent leur mode train normal. Cette différence découle du gel et fait
partie des conditions expérimentales déclarées.

T1 et T2 utilisent exclusivement
`EfficientNet_B0_Weights.IMAGENET1K_V1`, URL officielle
`https://download.pytorch.org/models/efficientnet_b0_rwightman-7f5810bc.pth`.
SHA256 complet fixé :
`7f5810bc96def8f7552d5b7e68d53c4786f81167d28291b21c0d90e1fca14934`.
Le fichier local est contrôlé intégralement avant chargement strict. Aucun
repli aléatoire T1/T2 et aucun téléchargement implicite. Un téléchargement
nécessite `--allow-download` ; un fichier hors ligne passe par
`--imagenet-weights`. Le chargement d'un checkpoint entraîné ne télécharge rien.

## Sources et anomalies synthétiques figées

Les manifestes déterministes existants sont conservés : train utilise seulement
les sources `split=train`, validation seulement `split=val`, dans les deux cas
images normales issues du `train/good` officiel. Les chemins et SHA256 de
contenu ne peuvent pas traverser les splits. Lire les métadonnées du manifeste
complet ne lit ni image ni masque test.

Chaque source donne exactement deux exemples : l'original label 0 et une
corruption localisée label 1, soit une proportion synthétique de 50 %. Le
générateur copie un patch de la même image, lui applique un contraste 0,8 ou
1,2 autour de sa moyenne par canal et un décalage local ±0,15, puis le colle
dans la zone valide. Les dimensions du rectangle sont tirées entre 10 et
30 % de la hauteur/largeur valides, avec arrondi supérieur. Cela correspond
approximativement à 1–9 % de la surface, sous réserve des arrondis.
Un repli garantit un changement sur les images uniformes. Le masque synthétique
est le support exact des pixels RGB modifiés ; le padding reste intact.

Les seeds de recettes dérivent de la seed d'expérience, du split, du chemin et
du SHA source. Elles ne dépendent ni du modèle, ni de son RNG, ni de l'époque.
Le plan JSON contient les paires, identifiants, seeds, SHA manifeste/config/code.
Il est immuable et revérifié par le Dataset. Les pixels sont rendus en mémoire
à chaque lecture, sans nouveau tirage. Un même plan est partagé par les trois
variantes pour une seed donnée. Les originaux restent intacts.

Le plan ne dépend pas des pixels, labels ou masques test. Les seuls donneurs
sont les images sources normales de leur propre split. Aucun mélange de
sources train/val, aucune texture externe, aucune anomalie industrielle réelle
utilisée pour construire ou sélectionner les corruptions.

## Prétraitement et budget communs

Même `letterbox_pair` que le projet : RGB [0,1], ratio conservé, bilinear,
padding zéro, résolution 256×256. Normalisation fixe ImageNet
`mean=[0.485,0.456,0.406]`, `std=[0.229,0.224,0.225]`, identique pour T0/T1/T2,
train, validation et futur test. Aucun calcul de statistiques MVTec test.
Une fonction inverse sert aux visualisations.

Cette normalisation reprend les constantes des poids torchvision. La géométrie
256×256 avec letterbox est une adaptation fixée au protocole du projet ; ce
n'est pas le resize/crop central 224×224 de la recette d'inférence ImageNet.
Aucune accuracy ImageNet publiée n'est revendiquée pour cette adaptation.

Catégories bottle, hazelnut et leather, un modèle indépendant par catégorie et
variante. Seed principale 42 ; extension possible 43 et 44, en exécutant toutes
les variantes sur chaque seed retenue. Les splits source ne changent jamais.
Pour une nouvelle seed, les recettes synthétiques et l'ordre des batches peuvent
changer, mais restent communs aux variantes : cette extension mesure donc aussi
la variabilité du jeu synthétique. Pas de sélection de la meilleure seed.

Budget commun : batch 16, maximum 20 époques, Adam avec betas (0,9 ; 0,999),
eps 1e-8 et weight decay zéro, FP32 sans AMP, workers 0, patience 5, min_delta 0.
Aucun scheduler. Le meilleur checkpoint minimise la BCE de validation
synthétique ; l'arrêt anticipé peut produire des durées/époques différentes.
La limite maximale et les autres réglages sont identiques ; seul le LR du
backbone T2 est différencié. Pas d'augmentation aléatoire supplémentaire.

Seeding Python/NumPy/Torch, DataLoader avec générateur indépendant, algorithmes
déterministes stricts, cuDNN benchmark désactivé. La reproductibilité ne promet
pas l'identité bit à bit entre CPU/CUDA ou versions de bibliothèques.

## Mesures et calibration

Chaque époque journalise loss, accuracy, AUROC, Average Precision, F1 et
TP/FP/FN/TN sur validation synthétique, ainsi que les mêmes descriptifs train.
Les courbes accuracy/F1 utilisent le seuil fixe 0,5. Les métriques train sont
accumulées pendant les mises à jour, en mode train ; elles ne constituent pas
une seconde évaluation figée du modèle.

Après sélection du meilleur checkpoint, la validation est réévaluée sans
augmentation. Le seuil est le quantile 95 % (`higher`) de ses seuls exemples
normaux ; décision strictement `score > seuil`. Il est recalculé par
modèle/catégorie/seed. Les exemples corrompus de val servent à mesurer les
métriques, pas à maximiser F1 ou à régler le seuil. L'objectif de FPR nominale
n'est pas une garantie de généralisation. La réutilisation de val pour
sélection/calibration limite l'indépendance de ces descriptifs.

Les AUROC/AP utilisent les scores continus. Une classe unique produit `null`
avec une raison explicite. F1 est `null` si son dénominateur est nul.
Des courbes d'apprentissage, ROC/PR, boxplots de scores et matrice de confusion
sont sauvegardés. Les paramètres entraînables sont comptés et nommés.

MLflow reste limité à une expérience locale `resilientinspect-transfer`, avec
tags variant/category/seed/scope/dataset_version/git_sha. Pas de Registry,
déploiement, DVC ou service supplémentaire. Chaque nouveau run conserve son
checkpoint best-val, état optimiseur, architecture/config effective,
normalisation, plan et SHA, code source, environnement et provenance ImageNet.

Sorties :
`artifacts/transfer_runs/<T0|T1|T2>/<catégorie>/seed<N>/<scope>_<runid>/`.
Fichiers : `best.pt`, `history.csv`, `summary.json`, `effective_config.yaml`,
`synthetic_plan.json`, `weight_provenance.json`, `trainable_parameters.json`,
`provenance.json`, `environment.json`, `data_usage.json`, `source/`,
`calibration.json`, `calibration.sha256`, `validation_predictions.csv`,
`validation_metrics.json`, `learning_curves.png`, `validation_diagnostics.png`.
Les outputs, données et résultats B0/A1 sont protégés, y compris les
contournements de destination par liens/jonctions testés.

## Grad-CAM

Couche cible explicite : `features.8.0`, convolution terminale 1×1 de 320 vers
1280 canaux, grille 8×8 à l'entrée 256×256. Grad-CAM utilise la moyenne spatiale
des gradients du **logit anomalie** (+logit), somme pondérée des activations,
ReLU puis interpolation bilinear et normalisation par carte. La classe normale
utilise -logit. Une carte nulle reste nulle, sans structure artificielle.

En T1, les entrées requièrent temporairement les gradients, ce qui permet une
attribution malgré le backbone gelé. Les modes, buffers, poids, gradients
préexistants et hooks du modèle sont préservés. La carte est une attribution
grossière de décision ; ce n'est **ni une segmentation, ni une carte d'erreur
AE, ni une probabilité pixel**. Aucun Dice/IoU/pixel-AUROC n'en est calculé.
Les cartes normalisées séparément ne comparent pas des amplitudes absolues.

Les smoke produisent `gradcam_synthetic.png` pour chaque variante, sur la même
paire source val, avec RGB, support connu de corruption, Grad-CAM et overlay.
La future revue réelle pourra placer les cartes AE déjà produites à côté de
ces attributions, avec leur provenance et des légendes distinctes, sans
réentraîner ni modifier les AE.

## Futur test réel soumis à revue

`src/evaluation/evaluate_transfer.py` et `configs/evaluate_transfer.yaml`
préparent une évaluation image sur le test réel, externe au domaine
synthétique. Ils refusent les smoke, checkpoints/calibrations périmés,
normalisations divergentes et validations incomplètes. Le SHA du protocole doit
être fourni explicitement avant toute lecture de checkpoint/manifeste/test
par la commande evaluate. Inspect ne construit aucun Dataset.

Le futur test calculera accuracy, AUROC, AP, F1, confusion et proportion réelle
d'anomalies, par variante/catégorie/seed, en conservant le seuil synthétique.
Il n'ouvre aucun masque officiel, inutile pour ces métriques image. Aucun
ajustement après observation du test. Une synthèse future utilisera les moyennes
macro par catégorie et toutes les seeds prévues, sans confondre les métriques
pixel AE et les métriques image des classifieurs. Les mesures de latence
p50/p95, mémoire et taille d'inférence feront l'objet du benchmark dédié §5.5 ;
elles ne sont pas revendiquées comme mesurées ici. Le temps d'un smoke local
n'est pas une mesure de latence d'inférence T4.

```powershell
# Exemple futur uniquement, une fois le run full et le protocole revus.
& .\.venv\Scripts\python.exe -m resilientinspect.evaluation.evaluate_transfer --stage inspect --run-dir "CHEMIN_RUN_FULL"
& .\.venv\Scripts\python.exe -m resilientinspect.evaluation.evaluate_transfer --stage evaluate --run-dir "CHEMIN_RUN_FULL" --approved-protocol-sha256 "SHA256_EXPLICITEMENT_VALIDE"
```

Le jeton d'approbation illustratif est volontairement invalide. Aucun appel
d'évaluation officielle n'est exécuté à cette étape.

## Commandes Kaggle préparées

Conserver le couple PyTorch CUDA/torchvision préinstallé. Vérifier d'abord les
imports et le GPU. Pour installer le projet et les outils manquants, figer
explicitement ces versions dans des contraintes, sans les extras locaux
`data` ou `transfer` :

```python
import importlib.metadata as md
from pathlib import Path
import subprocess
import sys
import torch
import torchvision

assert (3, 11) <= sys.version_info[:2] < (3, 14)
assert torch.cuda.is_available(), "Activer le GPU Kaggle ; aucun repli CPU."
protected = {name: md.version(name) for name in ("torch", "torchvision", "numpy")}
constraints = Path("/kaggle/working/transfer-runtime-constraints.txt")
constraints.write_text("".join(f"{name}=={value}\n" for name, value in protected.items()))
subprocess.run([sys.executable, "-m", "pip", "install", "-e", ".[train,eval,dev]",
                "-c", str(constraints)], check=True)
assert protected == {name: md.version(name) for name in protected}
print(torch.__version__, torchvision.__version__, torch.cuda.get_device_name(0))
```

Le notebook doit être positionné à la racine du dépôt. En cas de conflit de
dépendances, arrêter l'installation et revoir les contraintes ; ne pas
remplacer PyTorch CUDA. Localement, le test a ajouté seulement
torchvision 0.29.2+cpu sans dépendances, compatible avec torch 2.15.0+cpu déjà
installé. Les API utilisées existent aussi dans les versions compatibles du
runtime Kaggle ; leur exécution T4 reste à vérifier réellement.

Préparer un plan une fois par seed depuis les manifestes existants, puis lancer
chaque variante/catégorie séparément. Exemple Bash à adapter aux mounts Kaggle,
à exécuter **après revue** :

```bash
ROOT=/kaggle/input/VOTRE_DATASET/mvtec_ad
MANIFEST=/kaggle/input/VOS_MANIFESTES/manifest.csv
PLAN=/kaggle/working/transfer_data/seed42_plan.json
IMAGENET=/kaggle/input/VOS_POIDS/efficientnet_b0_rwightman-7f5810bc.pth
OUT=/kaggle/working/transfer_runs

python -m resilientinspect.data.synthetic --root "$ROOT" --manifest "$MANIFEST" --config configs/synthetic_transfer.yaml --seed 42 --output "$PLAN"

# Chaque appel cree un modele et un run independants. Pas d'evaluation test.
for category in bottle hazelnut leather; do
  python -m resilientinspect.training.train_transfer --config configs/train_t0.yaml --category "$category" --seed 42 --root "$ROOT" --manifest "$MANIFEST" --synthetic-plan "$PLAN" --output-dir "$OUT" --device cuda
  python -m resilientinspect.training.train_transfer --config configs/train_t1.yaml --category "$category" --seed 42 --root "$ROOT" --manifest "$MANIFEST" --synthetic-plan "$PLAN" --output-dir "$OUT" --device cuda --imagenet-weights "$IMAGENET"
  python -m resilientinspect.training.train_transfer --config configs/train_t2.yaml --category "$category" --seed 42 --root "$ROOT" --manifest "$MANIFEST" --synthetic-plan "$PLAN" --output-dir "$OUT" --device cuda --imagenet-weights "$IMAGENET"
done
```

Un smoke GPU préliminaire ajoute `--smoke` au même appel. Pour les seeds 43/44,
préparer un nouveau plan avec cette seed et changer `--seed` dans **tous** les
appels ; conserver les manifestes source. Les poids ImageNet peuvent être
attachés hors ligne ; `--allow-download` est une alternative explicite si
Internet est activé. T0 n'accepte aucun argument de poids préentraînés.

## Vérifications locales

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -W error --tb=short
& .\.venv\Scripts\python.exe -m resilientinspect.training.smoke_transfer --imagenet-weights artifacts/transfer_weights/efficientnet_b0_rwightman-7f5810bc.pth
& .\.venv\Scripts\python.exe -m pip check
```

Le lanceur smoke fabrique ses propres images et manifestes en dossier
temporaire, sans aucun test ni masque officiel, et garde toutes les ouvertures
d'images sous cette racine. Il exécute T0/T1/T2 sur CPU, seed 42, batch 2,
une époque et deux batches maximum par split, avec le même SHA de plan.
Il conserve des checkpoints et figures réels sous `artifacts/transfer_runs/`
et les preuves dans `reports/transfer/smoke_verification.json`. Un rapport
existant exige un nouveau chemin `--report`, sans écrasement.

Les preuves finales des tests, smoke, provenance et conservation sont dans
`reports/experiments/transfer_implementation_verification.json`.
Les métriques des smoke décrivent seulement les fixtures artificielles ; elles
ne mesurent pas la performance sur MVTec et ne servent à modifier aucun choix.

Résultat final : **462 tests réussis, 2 ignorés** (anciens tests CUDA B0/A1
sur cette machine CPU), warnings traités en erreurs. Les **119 nouveaux cas**
de cette phase réussissent. Les trois smoke CPU ont terminé, chacun avec deux
pas Adam, le même plan et les mêmes sources consommées ; les têtes ont changé,
les stages gelés sont intacts et les runs MLflow sont `FINISHED`. Les figures
Grad-CAM/diagnostics ont été examinées visuellement. `pip check` réussit.
Les **506 fichiers préexistants** contrôlés sont identiques en SHA256, taille
et date : 157 fichiers B0, 236 A1, 80 résultats B0/A1, 6 configurations,
21 sources et 6 fichiers de manifestes. Leurs inventaires protégés sont aussi
inchangés. Aucun entraînement réel complet ou test officiel à cette étape.

Sources primaires : [torchvision EfficientNet-B0](https://docs.pytorch.org/vision/main/models/generated/torchvision.models.efficientnet_b0),
[code EfficientNet torchvision](https://github.com/pytorch/vision/blob/main/torchvision/models/efficientnet.py),
[Grad-CAM](https://arxiv.org/abs/1610.02391),
[AUROC](https://scikit-learn.org/1.8/modules/generated/sklearn.metrics.roc_auc_score.html),
[AP](https://scikit-learn.org/1.8/modules/generated/sklearn.metrics.average_precision_score.html).

**Arrêt pour revue avant entraînement complet et évaluation officielle.**
