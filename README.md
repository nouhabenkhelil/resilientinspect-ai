# ResilientInspect AI

Projet de Deep Learning avancé, Axe 1 CNN et Transfer Learning. Le socle de la
phase 0 et la phase 1 (audit, préparation, EDA visuelle) sont validés. La
**phase 2, étape 2 couvre le pipeline d'entraînement B0 et son smoke CPU**,
autorisés le 7 novembre 2026. L'architecture B0 est validée. Un entraînement court
de vérification bottle/train et bottle/val est exécuté ; le run complet GPU,
A1 et T0/T1/T2 attendent une nouvelle validation.

## Référence et périmètre

Le guide technique v1.0 du 6 novembre 2026 a été lu intégralement, notamment les
sections 11 (arborescence), 15 (phases et preuves) et 16 (PowerShell).
Le fichier fourni est actuellement
[`resilientinspect-ai/guide_technique.docx.docx`](resilientinspect-ai/guide_technique.docx.docx),
et non `docs/guide_technique.docx`. Il est conservé à son emplacement d'origine.

Le dataset a été téléchargé localement par l'utilisateur dans
`data/raw/mvtec_ad/`. Les catégories **bottle, hazelnut, leather** sont maintenant
confirmées dans [`configs/dataset.yaml`](configs/dataset.yaml). Aucun
téléchargement automatique n'est effectué. Des manifestes séparent exclusivement
`train/good` en train/validation ; le Dataset redimensionne les images en mémoire.
Le test officiel est conservé ; aucune de ses images ou annotations n'est lue
par le pipeline d'entraînement ou de validation.

## Arborescence

`src/data/` contient l'audit, la préparation, le Dataset et l'EDA visuelle.
`src/models/autoencoder.py` contient B0. Les autres emplacements des phases
suivantes restent des dossiers vides ou des modules contenant une docstring,
à l'exception de `src/training/train_ae.py`, qui entraîne B0 par catégorie.

```text
.github/workflows/                # réservé
configs/dataset.yaml              # seed, splits et géométrie documentés
configs/ae_baseline.yaml          # architecture B0 et choix initial L1
configs/train_ae_b0.yaml          # protocole initial, Adam, early stopping, smoke
data/{raw,processed,manifests}/    # contenu exclu de Git
data/manifests/{manifest.csv,train.csv,val.csv,test.csv,preparation.json}
src/
  __init__.py
  {data,models,training,evaluation,export,mlops}/__init__.py
  data/{audit.py,prepare.py,dataset.py,eda.py}
  models/autoencoder.py
  training/train_ae.py
backend/{app/routes,tests}/        # réservé
frontend/src/{components,pages,services,styles}/  # réservé
tests/test_smoke.py
tests/test_audit.py
tests/{test_prepare.py,test_dataset.py}
tests/test_eda.py
tests/test_models.py
tests/test_training.py
reports/{eda,figures,tables,experiments,latex}/
  eda/{audit.json,audit_summary.csv,audit_by_defect.csv,layout_correction.json}
  eda/visual/                     # figures et constats locaux, ignores par Git
  experiments/decision_log.md
  experiments/{data_preparation.json,data_preparation_verification.json}
  experiments/b0_architecture_smoke.json
  experiments/b0_training_verification.json
scripts/{bootstrap.ps1,smoke_test.py}
artifacts/                        # contenu exclu de Git
pyproject.toml
.gitignore
.env.example
README.md
```

Pour respecter les chemins physiques du guide tout en exposant un espace de noms
Python propre, setuptools associe `src/` au paquet installé `resilientinspect`.
Exemple : `src/data/` s'importe avec `import resilientinspect.data`.
L'installation éditable est requise ; aucun ajout manuel à `PYTHONPATH`.

## Installation sous Windows PowerShell

Prérequis : Windows 11, Git et **Python 3.11 à 3.13 x64**. Le runtime local
réellement vérifié reste Python 3.11.9 ; l'exécution Python 3.13 sur Kaggle
reste à vérifier. Exécuter depuis la racine :

```powershell
Set-Location C:\Users\nouhe\resilientinspect-ai
git --version
py -0p

# Réutilise .venv s'il est valide, sinon recherche Python 3.11, 3.12 puis 3.13.
# RemoteSigned ne s'applique qu'à ce processus enfant.
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\bootstrap.ps1

# Installer le runtime CPU avant l'extra data (aucun poids de modèle).
& .\.venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.15.0+cpu"
& .\.venv\Scripts\python.exe -m pip install -e ".[dev,data,eda]"

& .\.venv\Scripts\python.exe --version
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe .\scripts\smoke_test.py
& .\.venv\Scripts\python.exe -m pytest -q -W error
```

Le bootstrap installe `.[dev]` dans `.venv`, sans activation, sans modifier la
stratégie d'exécution persistante et sans installer PyTorch/CUDA. `-SkipInstall`
permet de vérifier/créer seulement l'environnement. Un `.venv` existant invalide
est refusé et conservé. Le script fonctionne aussi depuis un autre répertoire.

Si aucun interpréteur pris en charge n'est trouvé, fournir son exécutable
explicitement (exemple local en 3.11) :

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\bootstrap.ps1 -PythonPath "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
```

Sur cette machine, le `.venv` Python 3.11.9 existe et fonctionne, tandis que
l'alias global `python` échoue et `py -0p` n'expose que Python Store 3.13.
Toujours employer l'exécutable explicite ci-dessus. Si une politique de groupe
interdit les scripts PowerShell, l'installation dans le `.venv` existant peut
aussi se faire directement :

```powershell
& .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -e ".[dev]"
```

Copie facultative de la configuration locale, sans écraser un fichier existant :

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
```

Les CLI de données utilisent `--root` explicitement et ne chargent pas `.env`.
Le smoke test du socle continue de fonctionner sans dataset.

## Dépendances et matériel

Le projet utilise [PyYAML 6.0.3](https://pypi.org/project/PyYAML/6.0.3/),
[Pillow 13.0.0](https://pypi.org/project/pillow/13.0.0/) pour le décodage et
[pytest 9.2.0](https://pypi.org/project/pytest/9.2.0/) pour les tests ; les versions
directes et le backend de construction sont fixés dans `pyproject.toml`.
L'extra `data` ajoute [PyTorch 2.15.0](https://pypi.org/project/torch/2.15.0/)
et [NumPy 2.3.5](https://pypi.org/project/numpy/2.3.5/). La roue CPU est installée
depuis l'[index officiel PyTorch](https://download.pytorch.org/whl/cpu/torch/).
L'extra `eda` fixe [Matplotlib 3.10.8](https://pypi.org/project/matplotlib/3.10.8/)
pour les figures scientifiques locales, avec rendu Agg sans interface graphique.
Ce fichier ne constitue pas encore un verrou complet des dépendances transitives.

L'audit du 6 novembre 2026 relève un AMD Ryzen 5 5500U (6 cœurs, 12 threads),
7 895 982 080 octets de RAM physique (~7,35 Gio), un GPU AMD Radeon(TM) Graphics
et Git 2.53.0.windows.1. Aucun GPU NVIDIA n'est déclaré par Windows et
`nvidia-smi` est absent du PATH. La valeur vidéo WMI de 512 Mio ne représente
pas toute la mémoire partagée du GPU intégré.

PyTorch est désormais requis pour l'étape `preparation`. Son absence ou une
erreur d'import fait échouer le smoke test et les tests Dataset, sans skip ni
filtre d'avertissement. Il reste facultatif dans les configurations historiques
du socle et de l'audit. Le runtime vérifié est `2.15.0+cpu`, sans CUDA ; le smoke
test vérifie un petit calcul CPU et l'import du module Dataset.

## Lire les vérifications

Le smoke test retourne un JSON avec la phase configurée, `status: "ok"` et un code de sortie
0 si Python 3.11, 3.12 ou 3.13 x64, le paquet installé, Git, les répertoires et la configuration
sont valides, sans accéder aux images. Un champ `status: "error"` et un code 1 identifient un contrôle en
échec. PyTorch absent est une erreur en préparation. Un dépôt sans commit est accepté
(`head: null`). Aucune sortie n'est une mesure de qualité d'un modèle.

Les tests vérifient notamment l'exécution du CLI depuis un autre répertoire,
le rejet de configurations incompatibles avec cette phase et les exclusions Git.
En cas d'erreur d'import, relancer l'installation éditable dans le même Python.
En cas d'erreur YAML, lire `checks.dataset_config.detail`. Pour conserver une
preuve locale (ignorée par Git) :

```powershell
& .\.venv\Scripts\python.exe .\scripts\smoke_test.py | Out-File -Encoding utf8 .\reports\experiments\environment_audit.json
git status --short --untracked-files=all
```

Les résultats réellement exécutés, les limites et décisions sont consignés dans
[`reports/experiments/decision_log.md`](reports/experiments/decision_log.md).

## Audit MVTec AD

Depuis la racine, après installation des dépendances :

```powershell
& .\.venv\Scripts\python.exe -m resilientinspect.data.audit --root data/raw/mvtec_ad --categories bottle hazelnut leather --output-dir reports/eda
& .\.venv\Scripts\python.exe -m pytest -q
```

L'auditeur ouvre les fichiers en lecture seule, calcule SHA256, applique
[`verify()` puis un décodage complet `load()`](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.verify),
et relève les résolutions natives, formats décodés et modes couleur. Il compte
séparément `train/good`, `test/good`, chaque défaut du test et les masques.
Les liens et jonctions ne sont pas suivis. Les répertoires manquants, requis vides,
les fichiers illisibles et les entrées de structure inattendues sont signalés.

Un masque correspond à une image uniquement si la catégorie, le défaut et le nom
`<stem>` / `<stem>_mask` concordent. Les appariements ambigus, masques manquants,
orphelins ou de dimensions différentes sont des erreurs. Les extensions reconnues
peuvent différer entre l'image et son masque. Les comptes incluent les fichiers
d'image corrompus ; les histogrammes concernent les fichiers décodables.
`matched_pairs` compte les appariements par nom, même si leur décodage ou taille
est invalide : consulter aussi les compteurs d'erreurs.

Les modes inhabituels de masque, valeurs non binaires, masques vides et doublons
exacts d'images sont des avertissements. La détection de doublons SHA256 est
effectuée à l'intérieur de chaque catégorie ; elle ne détecte pas les doublons
visuels réencodés. Le contrôle de taille image/masque ne prouve pas à lui seul
l'alignement sémantique de la segmentation.

Les rapports sont régénérés dans le répertoire de sortie, obligatoirement hors
du dataset :

- `audit_summary.csv` : synthèse par catégorie et distributions de dimensions/formats/modes.
- `audit_by_defect.csv` : effectifs et appariements par défaut.
- `audit.json` : synthèse, fichiers inspectés avec SHA256, erreurs et avertissements détaillés.
- `layout_correction.json` : preuve de la correction initiale de `bottle/bottle`, distincte de l'auditeur en lecture seule.

Le CLI retourne **0** sans erreur d'audit (avertissements possibles), **1** si des
anomalies bloquantes sont détectées avec rapports écrits, et **2** pour une erreur
d'exécution ou une destination de rapport interdite. Les chemins CLI relatifs
partent du répertoire courant. Le JSON contient la racine locale absolue du
dataset et des chemins de fichiers relatifs à cette racine.

L'imbrication initiale `bottle/bottle` a été normalisée sans écrasement : ses cinq
éléments ont été remontés dans `bottle/`. Le dossier d'emballage vide est conservé.
Les 1 393 fichiers, métadonnées comprises, ont conservé leurs contenus SHA256 et
dates de modification. L'auditeur sait aussi résoudre une imbrication non ambiguë
sans déplacer de fichier ; il refuse de choisir si les deux niveaux contiennent
des données de splits.

Les tests d'audit emploient uniquement de petites données synthétiques dans les
répertoires temporaires de Pytest. Aucun test automatisé ne dépend du dataset réel.

## Préparation déterministe et Dataset

```powershell
& .\.venv\Scripts\python.exe -m resilientinspect.data.prepare --root data/raw/mvtec_ad --output-dir data/manifests --report reports/experiments/data_preparation.json
& .\.venv\Scripts\python.exe -m pytest -q -W error
```

Les paramètres proviennent de `configs/dataset.yaml` (ou `--config`). Pour chaque
catégorie, les chemins de `train/good` sont triés, puis mélangés par un générateur
local `random.Random(42)` réinitialisé par catégorie. Les `ceil(0.2 × N)` premières
images constituent `val` ; les autres constituent `train`. L'arrondi supérieur
explique les petits écarts au ratio exact 80/20. L'ordre des catégories, des
fichiers sur disque et l'état du générateur aléatoire global n'affectent pas le
résultat. Aucun fichier officiel de test n'est réaffecté.

Les CSV UTF-8 utilisent des chemins POSIX relatifs à `data/raw/mvtec_ad` :
`image_path,category,split,label,defect_type,mask_path,source_split,sha256,mask_sha256`.
`label=0` signifie normal, `label=1` anormal ; les images normales ont un chemin
de masque vide. `source_split` conserve `train`/`test` officiel, y compris pour
les images de validation issues du train officiel. Les masques sont appariés
uniquement aux anomalies test correspondantes.

`manifest.csv` contient toutes les lignes ; `train.csv`, `val.csv`, `test.csv`
en sont des partitions. La validation refuse les chemins dupliqués, contenus
SHA256 identiques entre splits, anomalies en train/val, chemins hors racine et
masques incohérents. Une erreur d'audit ou un fichier ambigu/non reconnu dans les
splits bloque la préparation. Aucun fichier ne disparaît silencieusement.

Les CSV et `preparation.json` sont figés : une relance identique conserve leurs
octets et dates de modification. Une sortie existante différente est refusée
avant toute écriture ; pour un protocole futur autorisé, choisir un nouveau
répertoire de manifestes **et** un nouveau `--report`. Le rapport public conserve
effectifs, SHA256 des CSV, inventaire des sources et empreintes des deux scripts.
Les manifestes sous `data/` restent ignorés par Git, comme prévu par le guide.

```python
from resilientinspect.data.dataset import MVTecDataset

train = MVTecDataset("data/manifests/manifest.csv", "data/raw/mvtec_ad", split="train")
sample = train[0]  # lecture et transformation en mémoire uniquement
```

Le split est obligatoire ; utiliser de préférence le manifeste complet pour
vérifier la disjonction globale. Les originaux du split sélectionné ne sont ouverts
qu'à `__getitem__`. Leurs empreintes sont vérifiées par défaut avant décodage.

La sortie contient `image` float32 contiguë `[3,256,256]` et `mask` float32
binaire `[1,256,256]`, avec un masque nul pour les images normales. Le RGB est
converti par division fixe par 255, sans moyenne/écart-type calculé, sans
normalisation ImageNet et sans augmentation. Les labels et chemins sont retournés
avec `has_mask` et les métadonnées de géométrie.

La mise à taille est un **letterbox sans recadrage** : facteur commun
`min(256/H,256/W)`, dimensions arrondies au plus proche (demi vers le haut), puis
centrage avec bordures noires. Les images utilisent PIL BILINEAR ; les masques
utilisent NEAREST puis une conversion binaire `>0`, préservant leurs classes.
Une bordure impaire ajoute le pixel supplémentaire en bas ou à droite. Un
`valid_mask` distingue l'image utile des bordures ; `original_size`, `resized_size`
et `padding` permettent de retrouver la géométrie native. Les trois catégories
actuelles étant carrées, elles ne nécessitent aucune bordure.

Les masques test sont chargés uniquement avec `split="test"` pour un contrôle
d'alignement ou une future évaluation. Ils ne servent à aucun réglage ni calcul
de statistiques. Les tests synthétiques conservent les contrôles historiques du
socle et ajoutent non-fuite, reproductibilité, préservation du test, alignement,
chargement par DataLoader et détection d'originaux modifiés.

## EDA visuelle locale

```powershell
& .\.venv\Scripts\python.exe -m resilientinspect.data.eda --root data/raw/mvtec_ad --manifest data/manifests/manifest.csv --output-dir reports/eda/visual
& .\.venv\Scripts\python.exe -m pytest -q -W error
```

L'EDA lit les manifestes figés et vérifie leurs empreintes ainsi que celles des
images/masques. Elle n'écrit ni dans les originaux ni dans les manifestes. La
configuration, les scripts de préparation/Dataset, les splits et la géométrie
scientifique restent inchangés. Les mesures utilisent les pixels **natifs**, sans
passage à 256 × 256 et sans normalisation apprise.

Définitions : `Y'=(0.2126R+0.7152G+0.0722B)/255` sur RGB encodé, sans linéarisation
gamma ; il s'agit d'un proxy de luminance. La moyenne de Y' est calculée par
image, et le contraste RMS est son écart-type de population (`ddof=0`). Les
histogrammes distinguent train/good, val/good, test/good et test/anomaly. Les
distributions par image et les histogrammes agrégés de pixels sont séparés.
Les bornes d'affichage sont fixées à l'avance, sans choix de seuil sur le test.

La surface relative d'un masque est le nombre de pixels non nuls divisé par sa
surface native totale. Seuls les masques anormaux du test sont inclus ; les
images normales n'ajoutent pas de faux masques de surface zéro. Les boxplots par
défaut montrent les médianes, quartiles et valeurs extrêmes, avec axe logarithmique
si toutes les surfaces sont positives. Un masque touchant le bord est décrit,
sans être automatiquement considéré comme erroné.

Le dossier local contient :

- `{bottle,hazelnut,leather}_gallery.png` : normaux train/val/test, chaque type de
  défaut, masque binaire et superposition (rouge : annotation, jaune : contour).
- `{category}_distributions.png` : luminance moyenne, contraste, histogramme des
  pixels Y' et distribution des surfaces annotées.
- `{category}_alignment_XX.png` : toutes les paires anormales, 12 par planche,
  original et superposition côte à côte. Les crops sont uniquement des vues de
  contexte pour inspection, sans modification des images ou du Dataset.
- `image_statistics.csv`, `visual_eda_summary.json` : mesures natives, sélection
  déterministe, liste exhaustive des paires, coordonnées des crops et SHA256 des
  figures.
- `visual_review.json` : revue visuelle consignée après ouverture des figures,
  avec empreintes et portée de l'inspection ; le générateur ne prétend pas avoir
  réalisé automatiquement cette vérification sémantique.

Tout `reports/eda/visual/` est ignoré par Git, y compris les figures dérivées du
dataset. Le journal textuel conserve les constats et limites. L'égalité des
dimensions et une superposition visuellement plausible ne garantissent pas la
précision sémantique pixel par pixel des annotations. Aucune observation du test
n'est utilisée pour modifier les paramètres scientifiques ou entraîner un modèle.

## B0 : architecture et smoke test synthétique

`ConvAutoencoder` est un `torch.nn.Module` compact à **195 107 paramètres
entraînables**, sans skip connections ni poids préentraînés. Il attend un tenseur
flottant RGB `[B,3,256,256]`, avec B ≥ 1 et des pixels déjà divisés par 255.
Il ne modifie pas le prétraitement. Les autres dimensions sont refusées
explicitement, sans redimensionnement silencieux.

| Étape | Canaux × hauteur × largeur |
| --- | --- |
| Entrée | 3 × 256 × 256 |
| Encodeur 1 | 16 × 128 × 128 |
| Encodeur 2 | 32 × 64 × 64 |
| Encodeur 3 | 64 × 32 × 32 |
| Encodeur 4 / latent | 128 × 16 × 16 |
| Décodeur 1 | 64 × 32 × 32 |
| Décodeur 2 | 32 × 64 × 64 |
| Décodeur 3 | 16 × 128 × 128 |
| Reconstruction | 3 × 256 × 256 |

Chaque bloc encodeur applique Conv2d 3 × 3, stride 2, padding 1, BatchNorm2d,
ReLU. Le décodeur applique Upsample nearest ×2, Conv2d 3 × 3, padding 1,
BatchNorm2d, ReLU dans les trois blocs intermédiaires ; le dernier produit
3 canaux avec Sigmoid, donc des reconstructions dans [0,1]. Les convolutions
avant BatchNorm n'ont pas de biais ; la sortie RGB en possède un. BatchNorm
conserve les valeurs PyTorch par défaut : eps 1e-5, momentum 0.1, paramètres
affines et statistiques courantes. Initialisation PyTorch par défaut.

`configs/ae_baseline.yaml` fixe les canaux et la perte initiale
`torch.nn.L1Loss(reduction="mean")`, moyennée sur batch, canaux et pixels.
`model.kwargs` alimente le constructeur ; les autres champs décrivent le
contrat fixe de B0. La classe accepte trois ou quatre blocs, mais la baseline
configurée et vérifiée en utilise quatre. Aucun optimiseur, budget, seuil,
carte d'anomalie ou entraînement n'est implémenté à cette étape.

Smoke CPU indépendant du dataset, à exécuter depuis PowerShell avec le runtime
PyTorch déjà installé :

```powershell
@'
from pathlib import Path
import torch
import yaml
from resilientinspect.models.autoencoder import ConvAutoencoder

torch.manual_seed(42)
config = yaml.safe_load(Path("configs/ae_baseline.yaml").read_text(encoding="utf-8"))
model = ConvAutoencoder(**config["model"]["kwargs"]).to("cpu").train()
images = torch.rand(2, 3, 256, 256)
reconstruction = model(images)
loss = torch.nn.L1Loss(**config["loss"]["kwargs"])(reconstruction, images)
loss.backward()
assert reconstruction.shape == images.shape
assert torch.isfinite(reconstruction).all() and torch.isfinite(loss)
assert ((reconstruction >= 0) & (reconstruction <= 1)).all()
assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters())
print("CPU OK:", tuple(reconstruction.shape), sum(p.numel() for p in model.parameters()), "parametres")
'@ | & .\.venv\Scripts\python.exe -

& .\.venv\Scripts\python.exe -m pytest tests/test_models.py -q -W error
& .\.venv\Scripts\python.exe -m pytest -q -W error
```

Le 7 novembre 2026 : **22 tests B0 réussis, 1 test CUDA ignoré en 6,79 s** ;
suite complète : **136 réussites, 1 test CUDA ignoré en 34,40 s**. CPU vérifié
sur Python 3.11.9 et PyTorch 2.15.0+cpu ; CUDA reste à exécuter sur Kaggle/T4.
Le modèle utilise le device choisi par l'appelant (`model.to(device)` et
tenseurs sur le même device), sans dépendance CUDA imposée.

Les tests couvrent formes et plages en train/eval, batchs 1/2, images constantes,
gradients L1 finis jusqu'à l'encodeur, erreurs d'entrée et rechargement en mémoire
du state_dict avec les buffers BatchNorm. Le smoke de rétropropagation ne crée
aucun optimiseur et ne met pas à jour les poids. Les buffers BatchNorm d'une
instance jetable sont mis à jour par son passage en mode train. Le diagnostic
L1 sur bruit aléatoire n'est pas une mesure de qualité de reconstruction.
La preuve détaillée est dans `reports/experiments/b0_architecture_smoke.json`.

## Pipeline B0 : CPU smoke et Kaggle GPU

`src/training/train_ae.py` utilise B0 et `MVTecDataset` sans modifier leurs
implémentations. Un appel entraîne **une seule catégorie**, bottle par défaut,
avec une nouvelle initialisation du modèle et d'Adam. Hazelnut et leather
peuvent être choisis avec `--category`, dans des runs indépendants.

La configuration initiale `configs/train_ae_b0.yaml` fixe 256 × 256, batch size
16, maximum 20 époques, Adam (lr 0.001, betas 0.9/0.999, eps 1e-8, weight decay
0), L1 moyenne, patience 5, min_delta 0 et seed 42. AMP est désactivée ; activer
`mixed_precision` est refusé à cette étape. Ce sont des choix expérimentaux
initiaux, sans optimalité démontrée. Ils sont sauvegardés pour une future
comparaison contrôlée B0/A1 ; A1 n'est pas implémenté.

Seuls les Dataset `train` et `val` sont construits pour la catégorie demandée.
L'apprentissage met à jour les poids sur train ; val utilise `eval()` sans
gradient ni modification des buffers BN. Le meilleur checkpoint correspond au
minimum strict de L1 val, indépendamment de la perte train. L'early stopping
compte les époques sans amélioration supérieure à min_delta ; en cas d'égalité,
le premier checkpoint est conservé. La moyenne d'époque est pondérée par le
nombre d'images, pour traiter correctement le dernier batch incomplet.

Le manifeste complet figé et `preparation.json` sont requis. Lire ses métadonnées
ne charge aucune image test ; seuls les chemins des deux splits sélectionnés
sont ouverts, avec contrôle SHA256. Aucun score, seuil ou masque test n'est
utilisé. Le prétraitement letterbox 256 × 256, bilinear/nearest, pixels /255
est conservé ; la L1 porte sur tous les canaux/pixels, sans normalisation apprise.

Le déterminisme fixe Python, NumPy, PyTorch, les générateurs des DataLoader et
les workers ; cuDNN benchmark est désactivé et les algorithmes déterministes
sont requis. Les versions, le matériel, les sources, leur SHA256 et la seed sont
enregistrés. L'identité numérique entre versions, CPU et GPU n'est pas garantie
par [PyTorch](https://docs.pytorch.org/docs/2.15/notes/randomness.html).

Installation **locale**, avec PyTorch CPU déjà présent :

```powershell
& .\.venv\Scripts\python.exe -m pip install -e ".[train]"
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -W error -m resilientinspect.training.train_ae --config configs/train_ae_b0.yaml --root data/raw/mvtec_ad --manifest data/manifests/manifest.csv --category bottle --device cpu --output-dir artifacts/training --smoke
& .\.venv\Scripts\python.exe -m pytest -q -W error
```

L'extra `train` ajoute [mlflow-skinny](https://pypi.org/project/mlflow-skinny/3.16.1/),
SQLAlchemy 2.0.57, Alembic 1.20.1 et Matplotlib 3.10.8. Il ne déclare aucune
dépendance PyTorch : **ne pas installer l'extra `data` ni la roue CPU sur Kaggle**.
Le pipeline ne lance jamais pip. L'installation locale a conservé
PyTorch 2.15.0+cpu et les dépendances scientifiques précédentes.

Le mode `--smoke` surcharge uniquement le budget de vérification : une époque,
batch size 2, num_workers 0, **au plus deux mini-batches par split** (donc quatre
au total si train et val en contiennent assez). Il apprend réellement pendant
ces deux pas Adam, sur quatre images train au maximum. Il est marqué `scope=smoke`
dans les fichiers et MLflow ; sa validation partielle et son checkpoint ne
constituent pas un résultat d'expérience complète. En mode normal, tous les
batches train et val sont parcourus à chaque époque.

Chaque run reçoit un nouveau dossier `artifacts/training/<category>/<scope>_<run_id>/` :
`best.pt`, `history.csv`, `loss_curves.png`, `summary.json`, `data_usage.json`,
configuration effective, architecture, environnement, provenance et copies des
sources. Le checkpoint contient poids, état Adam, époque, perte val, catégorie,
scope, seed et configuration. Il se recharge avec
`torch.load(path, map_location="cpu", weights_only=True)` ; la reprise exacte
en milieu d'entraînement n'est pas implémentée.

MLflow suit l'expérience `resilientinspect-ae` dans une base SQLite locale
`artifacts/training/mlflow.db`, avec artefacts sous `mlartifacts/`. Paramètres,
séries train/val par époque, checkpoint, figures et sources sont enregistrés ;
un échec de boucle marque le run `FAILED`. Aucun serveur distant n'est utilisé.
Ces sorties restent ignorées par Git. Pour consulter les données sans serveur :

```python
from pathlib import Path
from mlflow import MlflowClient
uri = "sqlite:///" + (Path("artifacts/training/mlflow.db").resolve().as_posix())
client = MlflowClient(tracking_uri=uri)
experiment = client.get_experiment_by_name("resilientinspect-ae")
for run in client.search_runs([experiment.experiment_id]):
    print(run.info.run_id, run.info.status, run.data.tags, run.data.metrics)
```

Préparation **Kaggle/T4**, commandes fournies mais non exécutées ici : utiliser
le code du dépôt, les manifestes figés et le dataset existant, avec des chemins
adaptés au notebook. Le paquet autorise Python **>=3.11,<3.14**. L'environnement
Kaggle communiqué par l'utilisateur est Python **3.13.16**, PyTorch
**2.11.0+cu130**, Tesla T4 ; ces informations ne constituent pas une exécution
vérifiée depuis cette machine CPU. Choisir l'accélérateur GPU dans Kaggle,
puis conserver le runtime existant pendant l'installation :

```python
import sys
import subprocess
from pathlib import Path
from importlib.metadata import version, distributions
import torch

repo = Path("/kaggle/working/resilientinspect-ai")  # adapter au code fourni
assert (3, 11) <= sys.version_info[:2] < (3, 14), "Python 3.11 a 3.13 requis."
assert torch.cuda.is_available(), "Activer le GPU Kaggle ; aucun repli CPU implicite."
torch_before = version("torch")
print(torch_before, torch.version.cuda, torch.cuda.get_device_name(0))

# Contraindre les versions du runtime preinstalle : pip doit echouer plutot que le remplacer.
protected = {}
for distribution in distributions():
    name = distribution.metadata["Name"].lower().replace("_", "-")
    if name in {"torch", "torchvision", "torchaudio", "triton"} or name.startswith(("nvidia-", "cuda-")):
        protected[name] = distribution.version
constraints = Path("/kaggle/working/resilientinspect-runtime-constraints.txt")
constraints.write_text("\n".join(f"{name}=={value}" for name, value in sorted(protected.items())) + "\n", encoding="utf-8")
subprocess.run([sys.executable, "-m", "pip", "install", "--constraint", str(constraints),
                "-e", f"{repo}[train,eda,eval,dev]"], check=True)
assert all(version(name) == value for name, value in protected.items()), "Runtime CUDA modifie."
assert version("torch") == torch_before

# Verifications reelles a effectuer dans le notebook avant tout run complet.
subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
subprocess.run([sys.executable, "-m", "pytest", "-q", "-W", "error"], cwd=repo, check=True)

command = [sys.executable, "-m", "resilientinspect.training.train_ae",
           "--config", str(repo / "configs/train_ae_b0.yaml"),
           "--root", "/kaggle/input/VOTRE_DATASET/mvtec_ad",
           "--manifest", "/kaggle/input/VOS_MANIFESTES/manifest.csv",
           "--category", "bottle", "--device", "cuda",
           "--output-dir", "/kaggle/working/b0_runs"]
subprocess.run(command + ["--smoke"], cwd=repo, check=True)
# Apres validation du smoke GPU : meme commande sans --smoke pour le run complet.
```

Le 7 novembre 2026, le smoke réel bottle/CPU a traité **4 images train et
4 images val**, pertes L1 respectives **0.2950199544** et **0.3324028552**,
avec deux pas Adam et meilleur checkpoint à l'époque 1. Run MLflow
`b453d9b1af9d4186abcffa41afc10a87`, statut `FINISHED`. Ces pertes partielles
ne mesurent pas la qualité de détection. La suite finale donne
**156 passed, 1 skipped in 100.09s** ; le seul skip est CUDA indisponible.
Les tests vérifient notamment non-fuite, reproductibilité de deux runs
synthétiques, absence de mise à jour en validation, sélection val/early stopping,
rechargement du checkpoint, suivi MLflow réel et propagation des échecs.
Les résultats et limites sont consignés dans
`reports/experiments/b0_training_verification.json` et le journal.

## Compatibilité Python 3.11–3.13

La correction du 8 novembre 2026 élargit uniquement le contrat Python et ses
contrôles : `pyproject.toml`, smoke Python et bootstrap PowerShell acceptent
3.11, 3.12 et 3.13 en 64 bits. Les versions de dépendances restent inchangées,
ainsi que B0, ses configurations, le Dataset, les manifestes et les splits.
L'extra `data` reste réservé à la reproduction locale (torch 2.15.0) ; ne pas
l'installer sur le runtime CUDA Kaggle 2.11.0+cu130. Les extras `train,eda,dev`
ne demandent pas de paquet Torch/CUDA dans l'arbre de dépendances contrôlé.

Les métadonnées officielles des dix dépendances directes épinglées (backend de
construction inclus) autorisent Python 3.13.16 ; des roues Linux CPython 3.13,
abi3 ou universelles sont disponibles. En particulier,
[MLflow Skinny 3.16.1](https://pypi.org/project/mlflow-skinny/3.16.1/) et
[PyTorch 2.11.0](https://pypi.org/project/torch/2.11.0/) déclarent Python >=3.10.
L'[index officiel CUDA 13.0](https://download.pytorch.org/whl/cu130/torch/)
contient une roue `torch-2.11.0+cu130-cp313-cp313` Linux x86_64. Ces éléments
vérifient la disponibilité et les déclarations des paquets, pas l'exécution GPU.

Une résolution pip `--dry-run --python-version 3.13.16 --only-binary=:all:`
ciblant les roues Linux a réussi pour les dépendances épinglées hors PyTorch,
avec 62 paquets proposés et aucun paquet Torch/CUDA. Aucun paquet n'a été
installé par cette simulation. **Limite :** pip reste exécuté depuis Windows
Python 3.11 ; ses marqueurs d'environnement peuvent refléter l'hôte (par exemple
colorama). Ce résultat ne remplace donc pas `pip check`, les tests et le smoke
GPU dans le vrai notebook Python 3.13.16.

Les nouvelles vérifications conservent tous les tests précédents et ajoutent
les bornes Python, le contrôle x64, la concordance avec les métadonnées
installées, le probe PowerShell sans création de venv et l'absence de demande
Torch/CUDA par les dépendances Kaggle. Les preuves et résultats locaux sont
enregistrés dans `reports/experiments/python_compatibility.json`.
Vérification locale finale : **172 passed, 1 skipped in 93.57s** ; le seul skip
concerne CUDA indisponible. Les 50 tests ciblés de compatibilité/smoke passent
en 20.76 s ; bootstrap `-SkipInstall`, smoke du socle et `pip check` réussissent.
Python 3.13.16, PyTorch 2.11.0+cu130 et la T4 restent à vérifier réellement
dans Kaggle avant tout entraînement complet.

## Module d'évaluation B0 — protocole en revue

`src/evaluation/evaluate_ae.py` sélectionne un checkpoint B0 complet par catégorie
dans `artifacts/b0_runs/`, exclut smoke et doublons MLflow, vérifie les empreintes
et charge les poids en lecture seule. Plusieurs runs complets distincts pour une
catégorie provoquent une erreur explicite. Les configurations et splits existants
restent inchangés. Aucun entraînement n'est ajouté.

Le [protocole proposé](reports/experiments/b0_evaluation_protocol.md) et
`configs/evaluate_ae_b0.yaml` fixent une carte L1 RGB moyenne **sans lissage**, un
score image moyen sur les **1 %** d'erreurs valides les plus élevées, et deux
seuils **par catégorie** : quantile **95 %** des scores image val normale et
quantile **99,5 %** des erreurs pixel val normales. Quantiles `higher`, décision
stricte `>`, padding exclu. Ces choix attendent validation avant usage officiel.
La validation normale a déjà servi au choix du checkpoint ; sa réutilisation
pour calibrer les seuils est documentée, sans prétendre à une validation indépendante.

Commandes PowerShell depuis la racine, environnement PyTorch déjà installé :

```powershell
# L'extra eval n'impose aucune version de PyTorch.
& .\.venv\Scripts\python.exe -m pip install -e ".[eval,dev]"
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -m pytest tests/test_evaluation.py -q -W error --tb=short
& .\.venv\Scripts\python.exe -m pytest -q -W error --tb=short
# Inspection seule : aucun Dataset construit, aucune inference.
& .\.venv\Scripts\python.exe -m resilientinspect.evaluation.evaluate_ae --stage inspect --device cpu
```

Sur Kaggle, conserver les contraintes du runtime préinstallé présentées plus
haut et ajouter `eval` aux extras, sans installer l'extra `data`. Ce module n'a
pas été exécuté sur Python 3.13/CUDA/T4 depuis la machine locale.

**Commandes futures, à exécuter seulement après validation du protocole :**

```powershell
# Calibration : uniquement val normale, jamais test.
& .\.venv\Scripts\python.exe -m resilientinspect.evaluation.evaluate_ae --stage calibrate --device cpu
# Après accord sur CE YAML, conserver son empreinte exacte pour l'évaluation.
$approvedProtocolSha = (Get-FileHash -Algorithm SHA256 -LiteralPath configs/evaluate_ae_b0.yaml).Hash.ToLowerInvariant()
& .\.venv\Scripts\python.exe -m resilientinspect.evaluation.evaluate_ae --stage evaluate --device cpu --approved-protocol-sha256 $approvedProtocolSha
```

Les chemins sont adaptables avec `--runs-root`, `--root`, `--manifest`,
`--output-dir`, `--protocol` ; `--device cuda` demande un vrai GPU, sans repli
implicite. Sans empreinte approuvée et calibration compatible, le test est bloqué.
Une calibration modifiée ou un changement de code/protocole/manifeste/checkpoint
demande une nouvelle calibration avant toute inférence test. Aucun résultat
différent existant n'est écrasé ; utiliser un nouveau répertoire de sortie lors
d'un changement d'environnement ou de code.

Les sorties locales sous `reports/evaluation/b0/<SHA-protocole[:12]>/` comprennent
l'inventaire des checkpoints, les seuils/scores val, les prédictions CSV,
métriques JSON par catégorie, tableau CSV et moyenne macro, et figures PNG
entrée/reconstruction/heatmap/masque. Tout ce répertoire est ignoré par Git.
Les métriques préparées sont AUROC/AP image et pixel, confusion/F1 image,
Dice/IoU micro et descriptifs sur images anormales, avec conventions explicites
pour les valeurs indéfinies. Aucune recherche de seuil par Dice/IoU/F1 test.

L'implémentation est testée uniquement sur des images et checkpoints synthétiques
temporaires ; les poids Kaggle réels ont seulement été inspectés et chargés.
**Aucune calibration réelle ni évaluation du test officiel n'est exécutée à cette
étape.** Les preuves des vérifications sont dans
`reports/experiments/b0_evaluation_verification.json` et le journal des décisions.

## A1 résiduel — implémentation et smoke uniquement

Le candidat A1 est défini dans `configs/ae_improved.yaml` et
`configs/train_ae_a1.yaml`, avec un
[protocole figé avant test](reports/experiments/a1_protocol.md).
Encodeur/décodeur résiduels, canaux 32/64/128/256, latent 256×16×16,
**2 754 371 paramètres**, sortie Sigmoid. Deux skips seulement à 32×32 et 64×64,
projection 1×1 + tanh avec contribution bornée à ±0,1 ; aucun chemin RGB direct.
Cette limitation ne garantit pas qu'un défaut ne sera pas reconstruit.

La perte initiale est **0,8 L1 + 0,2 (1−SSIM)/2** : SSIM mono-échelle par canal
RGB, gaussienne 11×11 sigma=1,5, L=1, convolution valid. Sa validation numérique
CPU utilise une référence NumPy indépendante, des cas analytiques, des images
presque constantes et gradcheck ; elle ne démontre aucun gain de détection.
Les composantes L1/DSSIM et leur somme sont journalisées séparément.

Sur **train/good seulement**, probabilité 0,5 de faibles variations de luminosité
et contraste (facteurs 0,9 à 1,1), sans transformation géométrique. Tirages
reproductibles par seed/époque/index ; l'entrée augmentée est aussi la cible.
Val reste inchangée. Pas de statistique calculée sur test, pas de nouvelle
normalisation. Architecture, perte et augmentation peuvent être ablatées
indépendamment dans des copies de configuration ; une perte L1 seule exige
`name: l1`, poids 1/0 et `training.loss: l1` cohérents.

La boucle `src/training/train_ae.py` est commune à B0/A1. Les splits, résolution
256×256, seed 42, batch 16, maximum 20 époques, patience 5, Adam/LR 0,001 et
AMP désactivée restent identiques à B0. La sélection A1 utilise la **perte
composite val non augmentée**. Ne pas comparer sa valeur directement à la seule
L1 de B0. Aucun composant A1 n'est choisi d'après les scores du test B0.

Commandes PowerShell locales de reproduction (dépendances existantes inchangées) :

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_improved.py -q -W error --tb=short
& .\.venv\Scripts\python.exe -m pytest -q -W error --tb=short
& .\.venv\Scripts\python.exe -m pip check
# Smoke seulement : batch 2, une epoque, au plus deux batches train et val.
& .\.venv\Scripts\python.exe -m resilientinspect.training.train_ae --config configs/train_ae_a1.yaml --category bottle --device cpu --output-dir artifacts/a1_runs --smoke
```

Les sorties A1 sont séparées sous `artifacts/a1_runs/` et ignorées par Git.
Toute sortie dans les répertoires de poids/résultats B0 figés est refusée.
Les checkpoints embarquent l'architecture et les options loss/augmentation ;
`resilientinspect.training.a1_config.load_a1_checkpoint(path, device)` restaure
strictement cette architecture sauvegardée. MLflow utilise l'expérience commune
`resilientinspect-ae`, avec tag `variant=A1`, artefacts et code source hachés.

Kaggle, **après validation**, préparer un run indépendant par catégorie ; exemple
sans installation ni remplacement de PyTorch :

```python
import subprocess
import sys
from pathlib import Path
import torch

repo = Path("/kaggle/working/resilientinspect-ai")
assert (3, 11) <= sys.version_info[:2] < (3, 14)
assert torch.cuda.is_available(), "Activer le GPU ; pas de repli CPU."
category = "bottle"  # puis hazelnut et leather, chaque appel cree un nouveau modele
command = [sys.executable, "-m", "resilientinspect.training.train_ae",
           "--config", str(repo / "configs/train_ae_a1.yaml"),
           "--root", "/kaggle/input/VOTRE_DATASET/mvtec_ad",
           "--manifest", "/kaggle/input/VOS_MANIFESTES/manifest.csv",
           "--category", category, "--device", "cuda",
           "--output-dir", "/kaggle/working/a1_runs"]
subprocess.run(command + ["--smoke"], cwd=repo, check=True)
# Apres validation du smoke GPU, lancer un run complet par categorie :
# subprocess.run(command, cwd=repo, check=True)
```

Aucun paquet supplémentaire pour A1 : conserver la procédure d'installation
avec contraintes du runtime Kaggle présentée plus haut, extras `train,eda,eval,dev`,
jamais `data`. L'exécution Python 3.13/CUDA/T4 et la mémoire à batch 16 restent à
vérifier réellement. Un run A1 complet sur CPU est bloqué avant lecture d'images.

L'étape présente inclut seulement les tests et un smoke réel bottle CPU. Les
preuves, pertes de vérification et empreintes figurent dans
`reports/experiments/a1_implementation_verification.json` et le journal. Aucun
test A1 officiel n'est évalué et aucune amélioration sur B0 n'est annoncée.
La future comparaison gardera le même protocole de score/seuillage B0, avec des
seuils numériques recalibrés exclusivement sur val normale de chaque A1.

## Git et critères de validation

Git conserve le code, les configurations, les tests et les rapports textuels.
`.gitignore` exclut `.venv`, `.env` et ses variantes sensibles, les données,
archives, checkpoints, artefacts binaires et caches. Seuls les `.gitkeep` vides
préservent les répertoires de données/artefacts. Aucun ajout Git ni commit n'est
effectué automatiquement. Les protections Git sont testées sans créer de données.

L'étape de préparation est prête pour revue lorsque :

- la version Python x64 autorisée est identifiée et les capacités CPU/GPU sont documentées ;
- `pip check`, le smoke test et `pytest` réussissent sans dataset ;
- les exclusions Git protègent les chemins de données, poids et secrets ;
- les manifestes sont figés et les vérifications de splits/géométrie passent ;
- les effectifs réels et les limites figurent dans le journal.

Les contrôles du jeu test restent descriptifs jusqu'au gel du protocole.
Aucun entraînement ni réglage des seuils n'utilise le test. L'évaluation finale
B0 attend la validation explicite du protocole proposé ci-dessus.
