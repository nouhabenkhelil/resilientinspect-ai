# ResilientInspect AI

Projet de Deep Learning avancé, Axe 1 CNN et Transfer Learning. Le socle de la
phase 0 est validé. La **phase 1 est limitée ici à l'audit descriptif de MVTec AD**,
autorisé le 6 novembre 2026. Les expériences B0/A1 et T0/T1/T2 restent prévues,
sans modèle ni entraînement implémenté. Toute étape suivante nécessite une
nouvelle validation de l'utilisateur.

## Référence et périmètre

Le guide technique v1.0 du 6 novembre 2026 a été lu intégralement, notamment les
sections 11 (arborescence), 15 (phases et preuves) et 16 (PowerShell).
Le fichier fourni est actuellement
[`resilientinspect-ai/guide_technique.docx.docx`](resilientinspect-ai/guide_technique.docx.docx),
et non `docs/guide_technique.docx`. Il est conservé à son emplacement d'origine.

Le dataset a été téléchargé localement par l'utilisateur dans
`data/raw/mvtec_ad/`. Les catégories **bottle, hazelnut, leather** sont maintenant
confirmées dans [`configs/dataset.yaml`](configs/dataset.yaml). Aucun
téléchargement automatique n'est effectué. L'audit lit les images et les masques,
sans créer de manifeste d'apprentissage, split, transformation ou seuil.

## Arborescence

`src/data/audit.py` contient l'audit. Les autres emplacements des phases suivantes
restent des dossiers vides ou des modules contenant une docstring.

```text
.github/workflows/                # réservé
configs/dataset.yaml              # catégories confirmées, phase 1 audit
data/{raw,processed,manifests}/    # contenu exclu de Git
src/
  __init__.py
  {data,models,training,evaluation,export,mlops}/__init__.py
  data/audit.py
backend/{app/routes,tests}/        # réservé
frontend/src/{components,pages,services,styles}/  # réservé
tests/test_smoke.py
tests/test_audit.py
reports/{eda,figures,tables,experiments,latex}/
  eda/{audit.json,audit_summary.csv,audit_by_defect.csv,layout_correction.json}
  experiments/decision_log.md
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

Prérequis : Windows 11, Git et **Python 3.11 x64**. Exécuter depuis la racine :

```powershell
Set-Location C:\Users\nouhe\resilientinspect-ai
git --version
py -0p

# Réutilise .venv s'il est valide, sinon recherche Python 3.11 et le crée.
# RemoteSigned ne s'applique qu'à ce processus enfant.
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\bootstrap.ps1

& .\.venv\Scripts\python.exe --version
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe .\scripts\smoke_test.py
& .\.venv\Scripts\python.exe -m pytest -q
```

Le bootstrap installe `.[dev]` dans `.venv`, sans activation, sans modifier la
stratégie d'exécution persistante et sans installer PyTorch/CUDA. `-SkipInstall`
permet de vérifier/créer seulement l'environnement. Un `.venv` existant invalide
est refusé et conservé. Le script fonctionne aussi depuis un autre répertoire.

Si Python 3.11 n'est pas trouvé, fournir son exécutable explicitement :

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

Le CLI d'audit utilise `--root` explicitement et ne charge pas `.env`.
Le smoke test du socle continue de fonctionner sans dataset.

## Dépendances et matériel

Le projet utilise [PyYAML 6.0.3](https://pypi.org/project/PyYAML/6.0.3/),
[Pillow 13.0.0](https://pypi.org/project/pillow/13.0.0/) pour le décodage et
[pytest 9.2.0](https://pypi.org/project/pytest/9.2.0/) pour les tests ; les versions
directes et le backend de construction sont fixés dans `pyproject.toml`.
Ce fichier ne constitue pas encore un verrou complet des dépendances transitives.

L'audit du 6 novembre 2026 relève un AMD Ryzen 5 5500U (6 cœurs, 12 threads),
7 895 982 080 octets de RAM physique (~7,35 Gio), un GPU AMD Radeon(TM) Graphics
et Git 2.53.0.windows.1. Aucun GPU NVIDIA n'est déclaré par Windows et
`nvidia-smi` est absent du PATH. La valeur vidéo WMI de 512 Mio ne représente
pas toute la mémoire partagée du GPU intégré.

PyTorch n'est pas requis pour l'audit. S'il est déjà installé,
le smoke test vérifie un petit calcul CPU, interroge `torch.cuda.is_available()`
et teste chaque GPU CUDA annoncé avec un petit tenseur. Sinon il indique
`not_installed` et `cuda_available: null` : cela signifie **non testé**.
Le CPU reste la référence provisoire ; l'installation DL et le choix d'un
accélérateur seront décidés séparément, sur preuves matérielles.

## Lire les vérifications

Le smoke test retourne un JSON avec la phase configurée, `status: "ok"` et un code de sortie
0 si Python 3.11 x64, le paquet installé, Git, les répertoires et la configuration
sont valides, sans accéder aux images. Un champ `status: "error"` et un code 1 identifient un contrôle en
échec. PyTorch absent reste informatif. Un dépôt sans commit est accepté
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

## Git et critères de validation

Git conserve le code, les configurations, les tests et les rapports textuels.
`.gitignore` exclut `.venv`, `.env` et ses variantes sensibles, les données,
archives, checkpoints, artefacts binaires et caches. Seuls les `.gitkeep` vides
préservent les répertoires de données/artefacts. Aucun ajout Git ni commit n'est
effectué automatiquement. Les protections Git sont testées sans créer de données.

L'étape d'audit est prête pour revue lorsque :

- l'environnement Python 3.11 x64 est identifié et les capacités CPU/GPU sont documentées ;
- `pip check`, le smoke test et `pytest` réussissent sans dataset ;
- les exclusions Git protègent les chemins de données, poids et secrets ;
- les trois catégories sont auditées et les anomalies/limites figurent dans le journal.

Les contrôles du jeu test sont descriptifs. Aucun entraînement ni réglage des
seuils n'utilise le test. Les prochaines étapes de données, d'EDA visuelle et de
Deep Learning attendent une validation explicite.
