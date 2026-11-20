# Déploiement Docker Linux CPU

## Extension ONNX Runtime

PyTorch reste la référence FP32 et le moteur par défaut. `engine=pytorch`
ou `engine=onnxruntime` est un champ multipart facultatif des deux POST.
Une demande ONNX non admise renvoie HTTP 503 `onnx_unavailable`, sans repli.
La réponse indique `engine` et, pour une visualisation, `explanation_engine`.
Grad-CAM utilise toujours PyTorch ; sa cohérence avec le score ONNX est
vérifiée et une divergence injustifiée renvoie 409 `explanation_divergence`.

Les tolérances préalables sont dans [ONNX_PROTOCOL.md](ONNX_PROTOCOL.md).
Les exports/proofs sont montés en lecture seule sous `/app/artifacts/onnx`,
sans entrer dans l’image. Cache limité à deux sessions ORT réutilisées ;
threads inactifs sans spinning. Un échec ONNX ne retire pas un modèle PyTorch.

```powershell
& .\.venv\Scripts\python.exe -m pip install -r backend/requirements-onnx.txt
& .\.venv\Scripts\python.exe -m resilientinspect.export.onnx_cli export --models B0 T2 --categories bottle
& .\.venv\Scripts\python.exe -m resilientinspect.export.onnx_cli validate --models B0 T2 --categories bottle
# Après succès des pilotes, exporter/valider les quinze :
& .\.venv\Scripts\python.exe -m resilientinspect.export.onnx_cli export
& .\.venv\Scripts\python.exe -m resilientinspect.export.onnx_cli validate
```

Tout ajout Python sous `src/` ou `backend/app/` nécessite une nouvelle mesure
PyTorch Windows/Linux. Les anciennes preuves sont archivées localement sous
`deployment/reports/portability/archive/pre-onnx-9bb2c8d/`, exclues de Git.
Le validateur existant exécute explicitement PyTorch FP32 ; sa nouvelle preuve
n’est jamais substituée à une preuve ONNX. Renouveler d’abord ces preuves par
la procédure ci-dessous, puis ONNX Linux sur les mêmes sources finalisées :

```powershell
docker compose -f docker-compose.yml -f deployment/docker-compose.validation.yml run --rm --no-deps -T backend python -m resilientinspect.export.onnx_cli validate --dataset /validation --output /evidence/onnx-linux
# Benchmark : uniquement les modèles dont parity-linux.json indique passed.
# Exemple des deux pilotes, 20 warm-ups + 100 mesures par condition :
docker compose -f docker-compose.yml -f deployment/docker-compose.validation.yml run --rm --no-deps -T backend python -m resilientinspect.export.onnx_cli benchmark --models B0 T2 --categories bottle --dataset /validation --output /evidence/onnx-benchmark-linux
docker compose up -d --wait --wait-timeout 300
```

L’override hors ligne autorise l’écriture des nouvelles preuves ONNX dans le
dossier dérivé des exports. Les fichiers scientifiques originaux restent en
lecture seule. Ne jamais utiliser cet override pour servir l’application.
Une commande `validate` qui retourne 1 conserve les preuves failed et ne rend
pas les exports correspondants admissibles. Ne pas élargir les tolérances.

Les mesures et limites finales sont dans
`reports/experiments/onnx_benchmark.md` ; les valeurs publiques du frontend
sont un export agrégé, sans images ni chemins personnels.

Depuis la racine du dépôt, avec Docker Desktop en mode Linux :

```powershell
Set-Location C:\Users\nouhe\resilientinspect-ai
& .\.venv\Scripts\python.exe scripts/prepare_compose.py --check
$env:RI_FRONTEND_PORT = '18080'
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 240
Invoke-RestMethod http://localhost:18080/api/health
Start-Process http://localhost:18080
```

Arrêt du projet uniquement (sans suppression des données) :

```powershell
docker compose down
```

React : http://localhost:18080 ; API directe : http://localhost:8001/docs.
Le port public est configurable par `RI_FRONTEND_PORT`, avec défaut 18080.
Oracle TNSLSNR conserve le port 8080. Le backend local peut utiliser 8000
et Vite local 5173 comme auparavant.

## Admission scientifique

L’adaptateur `backend/app/portability.py` résout uniquement les chemins
canoniques `artifacts/<famille>_runs/<catégorie>/full_<run_id>/best.pt`, en
contrôlant identité, métadonnées et SHA256. Aucun chemin Windows archivé
n’est suivi ou réécrit. Les calibrations restent intactes. Les versions
numériques et réglages CPU doivent correspondre ; les champs OS/machine
restent dans la provenance. Un runtime Linux exige aussi le rapport de
parité dédié, lié aux sources, au manifeste, aux poids, aux calibrations
et au runtime exact. Les scores et décisions y sont revérifiés à l’admission.

Voir [le protocole préalable](PORTABILITY.md) et
[le compte rendu des mesures](reports/portability-verification.md).
Les preuves portent sur toute la validation normale, pas sur des images
arbitraires futures ni sur une nouvelle évaluation test.

## Reproduire les preuves Windows puis Linux

Les commandes n’entraînent aucun modèle et ne recalculent aucun seuil.
Elles lisent les images de validation autorisées et leurs SHA256. Le
programme hors ligne ne démarre pas FastAPI. Tout changement des codes
Python contrôlés nécessite de renouveler les preuves.

```powershell
& .\.venv\Scripts\python.exe -m deployment.validate_portability --phase windows --dataset data/raw/mvtec_ad --output deployment/reports/portability/windows.json
& .\.venv\Scripts\python.exe scripts/prepare_validation.py
docker compose build backend
docker compose -f docker-compose.yml -f deployment/docker-compose.validation.yml run --rm --no-deps -T backend python -m deployment.validate_portability --phase linux --dataset /validation --reference /app/deployment/reports/portability/windows.json --output /evidence/linux.json
```

L’override est réservé à cette commande hors ligne : il monte 170 images
val en lecture seule et le dossier de preuves en écriture sous `/evidence`.
Ne pas l’utiliser avec `up`. Le Compose normal ne monte aucune image MVTec.
Les rapports Windows/Linux et leurs empreintes sont sous
`deployment/reports/portability/`, hors des résultats officiels.

## Vérifications

```powershell
& .\.venv\Scripts\python.exe scripts/check_containers.py --output deployment/reports/container-portability-integration.json --frontend http://localhost:18080 --api http://localhost:8001
& .\.venv\Scripts\python.exe -m pytest tests/test_backend_api.py tests/test_compose_deployment.py tests/test_deployment_portability.py -q
npm.cmd --prefix frontend test
& .\.venv\Scripts\python.exe scripts/prepare_compose.py --check
docker compose ps
docker compose logs --tail 80 backend
```

Le test HTTP utilise une vraie image normale de validation par catégorie,
vérifiée par SHA256 ; il teste les quinze prédictions et leurs visualisations,
les seuils et décisions, les PNG, le proxy Nginx et les ressources React.
Aucun PNG artificiel ne sert de preuve de prédiction réussie.

## Montages et images

Les 273 fichiers scientifiques du plan généré restent en lecture seule,
avec `create_host_path: false`. Les preuves de déploiement sont également
montées en lecture seule dans le service. Les images Docker excluent datasets,
checkpoints, calibrations, secrets et preuves : seuls code et dépendances
sont incorporés. Les racines sont configurables via `RI_ARTIFACTS_DIR`,
`RI_MANIFESTS_DIR`, `RI_CONFIGS_DIR`, `RI_EVALUATION_DIR`, `RI_PORTABILITY_DIR`.
Le contexte des deux builds reste une liste d’inclusion explicite.

## Solution locale Windows

```powershell
& .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
# Dans un second terminal :
npm.cmd --prefix frontend run dev
```

Voir `frontend/README.md` pour la configuration Vite locale existante.
Aucun poids, seuil, source scientifique sous src/, configuration, manifeste
ou résultat officiel n’est modifié par cette livraison.
