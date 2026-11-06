# ResilientInspect AI

Projet de Deep Learning avancé, Axe 1 CNN et Transfer Learning. Ce dépôt contient
uniquement le socle de la **phase 0**. Les expériences scientifiques B0/A1 et
T0/T1/T2 sont prévues, sans implémentation, entraînement ni résultats à ce stade.
La phase 1 nécessite la validation explicite de l'utilisateur.

## Référence et périmètre

Le guide technique v1.0 du 6 novembre 2026 a été lu intégralement, notamment les
sections 11 (arborescence), 15 (phases et preuves) et 16 (PowerShell).
Le fichier fourni est actuellement
[`resilientinspect-ai/guide_technique.docx.docx`](resilientinspect-ai/guide_technique.docx.docx),
et non `docs/guide_technique.docx`. Il est conservé à son emplacement d'origine.

La phase 0 prépare Python/Git, la configuration, les répertoires et les tests du
socle. Elle ne télécharge pas MVTec AD, ne lit pas d'images, ne crée ni manifeste
ni split et ne calcule aucune métrique de modèle. Les catégories `hazelnut`,
`bottle`, `leather` restent **provisoires** : `confirmed: []` dans
[`configs/dataset.yaml`](configs/dataset.yaml).

## Arborescence

Les emplacements des phases suivantes sont uniquement des dossiers vides ou des
modules contenant une docstring. Aucun faux script d'entraînement, workflow CI,
service API, frontend, fichier DVC ou Docker n'est ajouté.

```text
.github/workflows/                # réservé
configs/dataset.yaml              # déclaration provisoire
data/{raw,processed,manifests}/    # contenu exclu de Git
src/
  __init__.py
  {data,models,training,evaluation,export,mlops}/__init__.py
backend/{app/routes,tests}/        # réservé
frontend/src/{components,pages,services,styles}/  # réservé
tests/test_smoke.py
reports/{eda,figures,tables,experiments,latex}/
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

Ces variables sont réservées aux phases suivantes. La phase 0 ne charge pas
`.env`, ne résout pas le chemin du dataset et n'exige pas sa présence.

## Dépendances et matériel

Le socle utilise [PyYAML 6.0.3](https://pypi.org/project/PyYAML/6.0.3/) et
[pytest 9.2.0](https://pypi.org/project/pytest/9.2.0/) pour les tests ; les versions
directes et le backend de construction sont fixés dans `pyproject.toml`.
Ce fichier ne constitue pas encore un verrou complet des dépendances transitives.

L'audit du 6 novembre 2026 relève un AMD Ryzen 5 5500U (6 cœurs, 12 threads),
7 895 982 080 octets de RAM physique (~7,35 Gio), un GPU AMD Radeon(TM) Graphics
et Git 2.53.0.windows.1. Aucun GPU NVIDIA n'est déclaré par Windows et
`nvidia-smi` est absent du PATH. La valeur vidéo WMI de 512 Mio ne représente
pas toute la mémoire partagée du GPU intégré.

PyTorch n'est pas requis pour valider cette phase. S'il est déjà installé,
le smoke test vérifie un petit calcul CPU, interroge `torch.cuda.is_available()`
et teste chaque GPU CUDA annoncé avec un petit tenseur. Sinon il indique
`not_installed` et `cuda_available: null` : cela signifie **non testé**.
Le CPU reste la référence provisoire ; l'installation DL et le choix d'un
accélérateur seront décidés séparément, sur preuves matérielles.

## Lire les vérifications

Le smoke test retourne un JSON avec `phase: 0`, `status: "ok"` et un code de sortie
0 si Python 3.11 x64, le paquet installé, Git, les répertoires et la configuration
sont valides. Un champ `status: "error"` et un code 1 identifient un contrôle en
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

## Git et critères de validation

Git conserve le code, les configurations, les tests et les rapports textuels.
`.gitignore` exclut `.venv`, `.env` et ses variantes sensibles, les données,
archives, checkpoints, artefacts binaires et caches. Seuls les `.gitkeep` vides
préservent les répertoires de données/artefacts. Aucun ajout Git ni commit n'est
effectué automatiquement. Les protections Git sont testées sans créer de données.

La phase 0 est prête pour revue lorsque :

- l'environnement Python 3.11 x64 est identifié et les capacités CPU/GPU sont documentées ;
- `pip check`, le smoke test et `pytest` réussissent sans dataset ;
- les exclusions Git protègent les chemins de données, poids et secrets ;
- les catégories demeurent provisoires et les limites figurent dans le journal.

La phase 1 reste bloquée par la validation explicite de l'utilisateur ; sa portée
et la confirmation des catégories seront traitées lors de cette validation.
