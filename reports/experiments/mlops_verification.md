# Vérification MLOps — 20 novembre 2026

Phase DVC / MLflow Tracking / Model Registry réalisée localement. Aucun
réentraînement, changement de poids, de seuil, de calibration ou de résultat
scientifique officiel. `pyproject.toml`, `src/`, `backend/app/`, les configurations
scientifiques et le validateur de portabilité restent inchangés. Aucun export,
benchmark ONNX ni preuve de portabilité réussie n’a été recalculé.

## DVC : versionnement, push et récupération réels

| Sortie | Fichiers | Octets logiques | Contenu |
|---|---:|---:|---|
| dataset | 1 392 | 1 299 864 929 | 1 162 images, 225 masques, cinq fichiers de manifeste/préparation |
| deployment | 506 | 607 441 993 | 15 checkpoints full, 14 graphes acceptés, calibrations, configurations, résultats, preuves, benchmark, bases MLflow historiques |
| Total | **1 898** | **1 907 306 922** | Copies indépendantes des originaux |

DVC **3.67.1**, cache `copy`, auto-staging désactivé. Deux pointeurs publics :
[`dataset.dvc`](../../mlops/dataset.dvc) et
[`deployment.dvc`](../../mlops/deployment.dvc). Les SHA256 individuels sont dans
[`release-manifest.json`](../../mlops/release-manifest.json). Le manifeste
officiel SHA256 `13f55c7cf7c87a3e3739e24920bb0d85cc96a39a00e30d277ddfaa1832b84522`
est conservé sans modification.

`dvc push` a réellement transféré **1 687 objets**, après déduplication, vers
`C:\Users\nouhe\resilientinspect-dvc-store`, hors du dépôt Git. Le cache et le
remote sont synchronisés. Une récupération `dvc pull` dans un nouveau dépôt
temporaire **avec cache vide** a téléchargé 1 687 objets et restauré les
1 898 fichiers. Les SHA256 des fichiers restaurés, des copies de livraison et
des originaux ont tous été contrôlés : **zéro divergence**. Aucun original n’a
été supprimé ou écrasé. Les reçus locaux sont conservés dans
`mlops/local/dvc-push.json` et `mlops/local/dvc-restoration.json`.

Un second contrôle a reconstruit les douze runs MLflow historiques depuis les
seuls fichiers récupérés par DVC : six jeux d’artefacts full canoniques rattachés,
six historiques smoke conservés comme métadonnées, paramètres et métriques.
Les artefacts smoke volontairement exclus ne sont pas réinventés. Les valeurs
et dates historiques restent identiques aux bases récupérées.

Le stockage local **n’est pas une sauvegarde hors machine**. Aucun stockage
cloud payant n’est configuré. Les octets des images test ont été lus pour leur
hachage et leur archivage DVC, sans nouvelle inférence ni réglage sur le test.

## Tracking : provenance et absence de doublons

MLflow **3.16.1**, backend SQLite persistant
`mlops/local/mlflow/tracking.db`, artefacts dans `mlops/local/mlflow/artifacts/`.
Les trois bases historiques restent byte-identiques. La consolidation préserve
leurs **douze UUID de runs**, paramètres, historiques, pas d’époque, timestamps,
dates de début/fin et statuts. Les URI d’artefacts sont relocalisées uniquement
dans la nouvelle copie ; les URI originales et empreintes des bases sont gardées.

| Groupe | Runs | Provenance |
|---|---:|---|
| B0/A1 full | 6 | Runs authentiques enregistrés pendant l’entraînement, réutilisés avec leurs UUID |
| T0/T1/T2 full | 9 | Imports rétrospectifs des résumés archivés ; identifiants originaux en tags ; valeurs réelles de chaque époque |
| Smoke historiques | 6 | Conservés pour consultation historique ; exclus des quinze modèles et de DVC |
| Technical-ONNX-Benchmark | 6 | Import technique des mesures CPU existantes, distinct des entraînements |
| Registry-Packaging | 3 | Conditionnement technique des trois checkpoints T2, sans entraînement |

Total : **30 runs**, dont quinze combinaisons full. Les relances de Tracking
ont réutilisé les mêmes clés sans créer de doublon. Les neuf imports full sont
étiquetés `retrospective_archive_import` ; leurs dates MLflow sont des dates
d’import, pas des dates d’entraînement. Les historiques ne contiennent que les
valeurs archivées. Aucune courbe manquante n’a été fabriquée.

Pour les quinze combinaisons, les métriques du test officiel sont des imports
étiquetés et préfixés `official_test.*`. Les paramètres, seed, checkpoint,
calibration, protocole et compatibilité ONNX sont associés par SHA256.
Les six benchmarks incluent les statistiques de score/forward, chargement,
mémoire, tailles et Grad-CAM lorsqu’applicables, ainsi que les fichiers bruts.
Les valeurs publiques sont comparées aux agrégats du benchmark source avant import.

Tableau complet : [`mlops_runs.csv`](mlops_runs.csv),
[`mlops_runs.json`](mlops_runs.json). Les résultats scientifiques sont repris
tels quels ; ils ne constituent pas une nouvelle évaluation.

## Registry : véritables modèles chargeables

| Modèle | Version | Alias | Images normales val | Erreur maximale de score | Décisions modifiées |
|---|---:|---|---:|---:|---:|
| ResilientInspect-T2-bottle | 1 | demo_candidate | 42 | 0 | 0 |
| ResilientInspect-T2-hazelnut | 1 | demo_candidate | 79 | 0 | 0 |
| ResilientInspect-T2-leather | 1 | demo_candidate | 49 | 0 | 0 |

T2/bottle a été conditionné en premier, puis hazelnut et leather. Chaque version
contient un vrai modèle MLflow PyFunc, le checkpoint authentique, l’architecture,
la calibration, le protocole, le résumé et les preuves ONNX Windows/Linux.
Les SHA256 sont vérifiés au chargement. Le conditionnement utilise le mécanisme
MLflow « models from code », sans sauvegarder un objet réseau picklé.

Les trois URI `models:/ResilientInspect-T2-<catégorie>/1` ont été téléchargées et
chargées réellement. Les artefacts récupérés ont les mêmes SHA256 que leurs
sources. L’inférence des versions récupérées a été comparée au chargeur
scientifique d’origine sur **170 images normales val**, avec les tolérances
existantes `atol=1e-5`, `rtol=1e-4` et les règles de décision inchangées.
Les trois URI d’alias ont également été chargées et leur sortie comparée.

L’alias n’a été affecté qu’après réussite de la vérification. Le modèle PyFunc
exécute PyTorch ; les tags ONNX décrivent la disponibilité dans l’application.
Contrat explicite : entrée normalisée `float32 [1,3,256,256]`, sortie score et
décision au seuil figé. Aucun téléchargement ImageNet n’est nécessaire.

**La sélection `demo_candidate` est rétrospective**, fondée sur les expériences
déjà observées, sans validation indépendante. Résultats détaillés dans
[`mlops_registry.json`](mlops_registry.json).

## Tests et accès réellement vérifiés

| Vérification | Résultat |
|---|---|
| Versionnement DVC, push, pull dans un cache vide | Réussis ; 1 898 SHA256 conformes |
| Récupération Tracking depuis les fichiers DVC | 12 runs historiques préservés, 6 jeux full rattachés |
| Chargement Registry par version et alias | Trois modèles, 170 images val, écart maximal nul |
| Tests MLOps | **5 réussis** : intégrité de restauration, remote hors Git, protection des originaux, refus d’écrasement et rejet d’un checkpoint corrompu |
| Dépendances MLOps | `pip check` : aucune dépendance incompatible ; setuptools 80.9.0 et wheel 0.45.1 figés dans l’environnement isolé |
| Régression backend/ONNX/portabilité/Compose | **69 réussis**, dont neuf tests ONNX |
| FastAPI réel via Nginx | Huit POST 200 : B0/T2 × PyTorch/ORT × predict/visualize ; moteur invalide 422 ; T1/bottle ORT 503 sans repli |
| Disponibilité réelle | **15 PyTorch et 14 ONNX** ; health et metadata vérifiés |
| MLflow HTTP | Interface et API locales accessibles sur 127.0.0.1:5000 |
| Chromium réel | Cinq écrans vérifiés : expériences, paramètres/métriques, artefacts, Registry, version détaillée ; zéro erreur JavaScript |
| Entrées scientifiques Docker | **273 fichiers inchangés**, contrôle SHA256 du plan de montage réussi |
| Code et preuves existantes | Empreintes PyTorch et ONNX conformes au code courant ; environnement scientifique Windows inchangé |

Le parcours navigateur ferme la fenêtre d’accueil du Registry avant navigation.

Commandes de test :

```powershell
.\.venv-mlops\Scripts\python.exe -m pytest mlops/tests -q --tb=short
.\.venv-mlops\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest tests/test_onnx_export.py tests/test_backend_api.py tests/test_deployment_portability.py tests/test_compose_deployment.py -q --tb=short
.\.venv\Scripts\python.exe scripts/prepare_compose.py --check
.\.venv\Scripts\python.exe scripts/check_onnx_api.py
.\.venv-mlops\Scripts\python.exe mlops/tracking.py verify
node mlops/browser-qa.mjs
.\.venv-mlops\Scripts\python.exe mlops/verify.py
docker compose ps
```

Le frontend React est inchangé ; ses tests et son build de la phase ONNX n’ont
pas été répétés pour cette phase MLOps. Rapports :
[`mlops_browser.json`](mlops_browser.json),
[`mlops_verification.json`](mlops_verification.json),
[`onnx-http.json`](../../deployment/reports/onnx-http.json).

## État final et démonstration

| Service | État observé | Accès |
|---|---|---|
| resilientinspect-backend-1 | running / healthy | 127.0.0.1:8001 |
| resilientinspect-frontend-1 | running / healthy | http://localhost:18080 |
| MLflow local PowerShell | running, HTTP 200 | http://127.0.0.1:5000 |
| Oracle | Port 8080 toujours en écoute | Inchangé |

MLflow est indépendant de FastAPI, sans ajout au Compose principal ni arrêt des
conteneurs existants. Le guide PowerShell et le parcours de démonstration sont
dans [`mlops/README.md`](../../mlops/README.md). Lancer l’interface avec
`.\mlops\serve.ps1`, puis sélectionner **Model training**.

Liste exacte à publier : [`mlops_publish_files.txt`](mlops_publish_files.txt).
Les poids, données MVTec, exports ONNX, SQLite, environnements, caches, artefacts
MLflow et sorties DVC ne sont pas candidats Git. Aucun commit ni push GitHub
n’est réalisé par cette mission.

## Limites restantes

- Remote DVC et Registry restent locaux à cette machine ; sauvegarde externe à prévoir.
- Le serveur et les URI d’artefacts utilisent des chemins locaux ; après déplacement,
  rejouer le bootstrap et reconstruire ou migrer la copie locale MLflow, en préservant
  les bases historiques.
- Seuls les trois T2 sont conditionnés dans le Registry ; les quinze full sont
  consultables dans Tracking. Le PyFunc ne fournit pas le décodage d’image ou Grad-CAM.
- T1/bottle reste refusé avec ONNX ; aucune tolérance n’a été élargie.
- Les mesures ONNX restent celles de la machine CPU partagée, sans extrapolation à
  un environnement de production.
- Les imports et la sélection des candidats sont rétrospectifs ; aucune validation
  indépendante supplémentaire n’est revendiquée. CI/CD hors périmètre.
