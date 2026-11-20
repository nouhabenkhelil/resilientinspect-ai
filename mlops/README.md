# DVC et MLflow locaux

Implémentation du 20 novembre 2026, Python 3.11.9. Aucun entraînement, aucun
changement de poids, de seuil, de calibration, de `pyproject.toml`, de `src/` ou
de `backend/app/`. L’application reste sur **http://localhost:18080** et ne
dépend pas de MLflow. Oracle et le port 8080 sont préservés. Pas de CI/CD.

## Environnement PowerShell

Depuis la racine du dépôt :

```powershell
.\mlops\bootstrap.ps1
```

Le script crée `.venv-mlops`, ajoute en lecture les paquets de la `.venv`
scientifique existante via un fichier `.pth`, puis installe **DVC 3.67.1 et
MLflow 3.16.1** dans le nouvel environnement. Les versions résolues figurent
dans `requirements-lock.txt`. Les versions déjà présentes dans `.venv` sont
contraintes ; cette `.venv` n’est pas modifiée. Ce montage local exige de
rejouer le bootstrap après déplacement du dépôt. Il ne constitue pas un
environnement autonome exportable : préparer d’abord la `.venv` scientifique
avec les dépendances figées du projet.

## DVC : contenu et stockage

Deux sorties indépendantes, exclues de Git :

| Pointeur Git | Sortie locale | Contenu |
|---|---|---|
| `mlops/dataset.dvc` | `mlops/dataset/` | 1 392 fichiers : 1 162 images, 225 masques, cinq manifestes et préparation officiels |
| `mlops/deployment.dvc` | `mlops/deployment/` | 506 fichiers : 15 checkpoints full, configurations/sources archivées, calibrations, résultats, preuves Windows/Linux, benchmark, trois bases MLflow historiques et 14 graphes ONNX acceptés |

T1/bottle : métadonnées et preuves d’échec conservées, graphe refusé exclu.
Les checkpoints smoke, doublons de poids MLflow, caches et images de diagnostic
ne font pas partie de la livraison. Le manifeste officiel reste inchangé ;
`release-manifest.json` ajoute une empreinte SHA256 de chaque fichier livré.
Les identifiants MD5 utilisés par DVC ne remplacent pas ces contrôles SHA256.

Les sorties sont des **copies vérifiées**. DVC ne gère ni ne remplace directement
les originaux `data/`, `artifacts/` et `reports/`. Le cache utilise `copy`, sans
lien dur aux originaux. La livraison représente **1 907 306 922 octets logiques**,
avant déduplication du stockage DVC.

```powershell
# Vérifie les sources figées, prépare les copies et leurs pointeurs.
.\.venv-mlops\Scripts\python.exe mlops/dvc_release.py stage

# Choisir un dossier hors du dépôt, sur un volume accessible.
# Valeur utilisée et réellement testée sur cette machine :
$artifactRemote = Join-Path (Split-Path (Get-Location).Path -Parent) 'resilientinspect-dvc-store'
.\.venv-mlops\Scripts\python.exe mlops/dvc_release.py push --remote $artifactRemote

# Commandes DVC directes : la configuration personnelle reste dans .dvc/config.local.
.\.venv-mlops\Scripts\python.exe -m dvc remote add --local --force --default local_store $artifactRemote
.\.venv-mlops\Scripts\python.exe -m dvc status
.\.venv-mlops\Scripts\python.exe -m dvc status --cloud
.\.venv-mlops\Scripts\python.exe -m dvc push
.\.venv-mlops\Scripts\python.exe -m dvc pull
.\.venv-mlops\Scripts\python.exe -m dvc checkout
.\.venv-mlops\Scripts\python.exe mlops/dvc_release.py verify
```

`pull` télécharge dans le cache puis restaure les deux sorties ; `checkout`
restaure depuis le cache les versions désignées par les pointeurs du commit
courant. Ces opérations concernent les copies de livraison. Ne pas placer de
travail manuel dans ces sorties. Sur une autre machine, configurer aussi un
cache de métadonnées accessible à l’utilisateur si nécessaire :

```powershell
.\.venv-mlops\Scripts\python.exe -m dvc config --local core.site_cache_dir "$((Get-Location).Path)/.dvc/site-cache"
```

Le stockage utilisé est `C:\Users\nouhe\resilientinspect-dvc-store`, hors du
dépôt et configurable. **Ce stockage local n’est pas une sauvegarde hors
machine.** Aucun cloud payant n’est configuré. La base Registry en activité
reste dans `mlops/local/mlflow/` ; elle n’est pas une sortie DVC mutable.

## Récupération sans écraser les originaux

```powershell
# Crée un nouveau dépôt DVC sans Git et un cache vide dans %TEMP%, lance pull,
# contrôle tous les SHA256 restaurés, les copies et les originaux.
.\.venv-mlops\Scripts\python.exe mlops/dvc_release.py restore

# Après pull, rétablir les chemins canoniques dans un AUTRE checkout du même code.
# La commande refuse le dépôt original, les liens dangereux et tout fichier différent.
.\.venv-mlops\Scripts\python.exe mlops/dvc_release.py materialize --destination C:\recovery\resilientinspect-ai
```

Le dossier temporaire de contrôle est conservé ; son chemin figure dans
`mlops/local/dvc-restoration.json`. Les sorties de livraison ne contiennent pas
le code courant complet : utiliser le même commit Git, dont les empreintes sont
liées aux preuves Docker. `materialize` ne lance aucun recalcul scientifique.

## MLflow Tracking et Registry

```powershell
.\.venv-mlops\Scripts\python.exe mlops/tracking.py track
.\.venv-mlops\Scripts\python.exe mlops/tracking.py verify
.\.venv-mlops\Scripts\python.exe mlops/registry.py register
# Vérification explicite, seulement si nécessaire : recharge les URI et infère sur val.
.\.venv-mlops\Scripts\python.exe mlops/registry.py verify

# Serveur au premier plan ; Ctrl+C arrête ce serveur uniquement.
.\mlops\serve.ps1
# Si 5000 est occupé, choisir un autre port explicitement :
.\mlops\serve.ps1 -Port 5001
```

Ouvrir **http://127.0.0.1:5000** et sélectionner **Model training** en haut.
La base persistante est `mlops/local/mlflow/tracking.db` (SQLite) ; les artefacts
sont dans `mlops/local/mlflow/artifacts/`. Garder les deux ensemble. Après un
déplacement de ces dossiers, les URI absolues nécessitent une migration des
copies locales ou une reconstruction avec les scripts. Ne pas modifier les
bases historiques pour corriger leurs anciens chemins.

Les trois bases historiques sont ouvertes en lecture seule. Une nouvelle base
consolide leurs douze runs avec les UUID, paramètres, pas d’époque, dates et
historiques exacts. Seules les URI d’artefacts des copies locales sont relocalisées,
avec l’URI d’origine conservée dans les tags. La migration contrôle l’égalité
des schémas des tables copiées ; un changement de schéma exige une revue.
Elle refuse d’écraser une base centrale sans audit.

Six runs full B0/A1 sont réutilisés. Les neuf full Transfer absents des bases
sont importés depuis les résumés authentiques, avec
`ri.provenance=retrospective_archive_import`, identifiant d’origine, SHA256 du
résumé et dates d’import explicites. Les historiques contiennent les valeurs
archivées, sans interpolation ni reconstruction de métriques absentes. Les
métriques du test officiel sont préfixées `official_test.*` et étiquetées comme
imports rétrospectifs pour les quinze modèles. Leurs dates d’import ne sont pas
des dates d’évaluation. Les six smoke restent consultables comme historique,
sans participer aux quinze modèles ni à la livraison DVC. Après récupération
DVC, leurs métadonnées subsistent ; leurs artefacts smoke exclus ne sont pas
recréés. Les full peuvent rattacher leurs fichiers canoniques récupérés.

`Technical-ONNX-Benchmark` contient six runs issus des mesures CPU déjà
réalisées, séparés des entraînements. `Registry-Packaging` contient trois runs
techniques de conditionnement. La relance de Tracking réutilise les clés de
provenance ; une version Registry déjà compatible est réutilisée. Un changement
du code de conditionnement ou de ses sources produit une autre empreinte de
paquet et requiert une nouvelle version, sans remplacer les versions existantes.

Le tableau des quinze combinaisons est disponible en
[JSON](../reports/experiments/mlops_runs.json) et [CSV](../reports/experiments/mlops_runs.csv).

## Démonstration en cinq étapes

1. Dans **Experiments**, ouvrir `Historical-B0` ou `Historical-A1` : run full,
   historique de loss original, paramètres et tags de provenance.
2. Ouvrir `Archived-Transfer-Imported`, puis `T2-bottle-archived-full-seed42` :
   tags d’import, paramètres, `train_loss`, `val_loss`, métriques `official_test.*`.
   Dans **Artifacts**, ouvrir `frozen_evidence` pour le checkpoint, le résumé,
   le protocole et la calibration authentiques.
3. Ouvrir `Technical-ONNX-Benchmark` : comparer les six lignes B0/T2, les
   latences p50/p95, le facteur calculé sur les moyennes et le CSV de mesures.
4. Dans **Model registry**, fermer la fenêtre d’accueil si elle apparaît.
   Ouvrir `ResilientInspect-T2-bottle`, **Version 1** : alias `demo_candidate`,
   empreintes des poids/calibration/protocole, compatibilité ONNX et lien du run
   technique de conditionnement. Répéter pour hazelnut et leather.
5. Montrer les résultats de récupération et d’inférence dans
   [mlops_registry.json](../reports/experiments/mlops_registry.json), puis
   l’application sur 18080 : 15 PyTorch, 14 ONNX, T1/bottle ONNX indisponible.

Les trois versions sont de vrais modèles **MLflow PyFunc chargeables** avec
checkpoint original, architecture, calibration, protocole et preuves embarqués.
Le PyFunc exécute **PyTorch** ; le tag `ri.available_engines` décrit les moteurs
validés dans l’application, pas deux flavors exécutables dans MLflow.
L’entrée est un tenseur `float32 [1,3,256,256]`, RGB letterbox puis normalisation
ImageNet ; la sortie est `[score, decision]`. L’API existante reste responsable
du décodage d’image et des explications.

```powershell
@'
import mlflow
import numpy as np
from pathlib import Path
mlflow.set_tracking_uri('sqlite:///' + (Path.cwd() / 'mlops/local/mlflow/tracking.db').as_posix())
model = mlflow.pyfunc.load_model('models:/ResilientInspect-T2-bottle@demo_candidate')
# Exemple de contrat, pas une image ni une mesure scientifique.
print(model.predict(np.zeros((1, 3, 256, 256), dtype=np.float32)))
'@ | .\.venv-mlops\Scripts\python.exe -
```

**Sélection rétrospective** fondée sur des expérimentations déjà observées,
sans validation indépendante. Aucun seuil n’est choisi ou ajusté ici.

## Vérifications et publication

```powershell
.\.venv-mlops\Scripts\python.exe -m pytest mlops/tests -q
.\.venv\Scripts\python.exe scripts/prepare_compose.py --check
.\.venv\Scripts\python.exe scripts/check_onnx_api.py
node mlops/browser-qa.mjs
.\.venv-mlops\Scripts\python.exe mlops/verify.py
docker compose ps
```

La QA navigateur utilise le Playwright déjà installé dans `frontend/`, sans
modifier React. Captures locales dans `mlops/local/screenshots/`, exclues de Git.
Le service MLflow est volontairement lancé par PowerShell : les chemins
scientifiques Windows historiques n’ajoutent aucune dépendance au Compose de
service Linux. Un Compose MLflow optionnel n’apporterait pas de bénéfice pour
cette démonstration locale ; aucun n’est nécessaire au fonctionnement actuel.

Publier uniquement les fichiers de
[mlops_publish_files.txt](../reports/experiments/mlops_publish_files.txt).
Les données MVTec, poids, ONNX, caches, bases SQLite, `mlruns`, artefacts MLflow,
environnements et sorties DVC sont exclus de Git. Le stockage DVC et la base
Registry nécessitent une stratégie de sauvegarde externe ultérieure.

Références : [DVC add](https://doc.dvc.org/command-reference/add),
[configuration DVC](https://doc.dvc.org/user-guide/project-structure/configuration),
[MLflow PyFunc](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.pyfunc.html),
[backend SQLite MLflow](https://mlflow.org/docs/latest/tracking/backend-stores/).
