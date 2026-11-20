# API CPU ResilientInspect AI

## Moteurs PyTorch et ONNX Runtime

Les requêtes existantes restent valides : le moteur par défaut est `pytorch`.
Les deux POST acceptent le champ multipart facultatif `engine` avec les
valeurs `pytorch` ou `onnxruntime`. Les réponses identifient toujours le moteur
réellement employé. Aucun repli automatique n’est effectué.

`GET /health` expose `ready_models_by_engine`. Les métadonnées fournissent
`available_engines`, `engine_validation` et `engine_unavailable_reasons` par
modèle. Un export absent, périmé ou en échec de parité ne retire pas son
équivalent PyTorch et ne peut pas être choisi comme moteur ONNX.

L’admission vérifie les SHA256 du graphe et de sa métadonnée, les liaisons
checkpoint/calibration, les codes sources, le manifeste et une preuve ONNX
produite dans l’environnement courant. Les sessions CPU utilisent deux
threads et un cache partagé limité à deux sessions. Un moteur indisponible
retourne HTTP 503 `onnx_unavailable` ; une valeur inconnue retourne 422.

B0/A1 expliquent la reconstruction du moteur choisi. T0/T1/T2 conservent
Grad-CAM PyTorch : une prédiction ONNX retourne alors
`explanation_engine=pytorch`, le score PyTorch associé, l’état de cohérence
et le temps d’explication. Une divergence hors politique retourne 409
`explanation_divergence`. Les coordonnées letterbox et PNG sont inchangés.

Installer les dépendances facultatives ONNX :

```powershell
& .\.venv\Scripts\python.exe -m pip install -r backend/requirements-onnx.txt
```

Voir `deployment/ONNX_PROTOCOL.md` pour les tolérances et
`reports/experiments/onnx_benchmark.md` pour les mesures réelles.

Depuis la racine du dépôt, avec le venv scientifique local déjà installé,
installer les dépendances HTTP puis démarrer le service dans PowerShell.

```powershell
Set-Location C:\Users\nouhe\resilientinspect-ai
& .\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
& .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Ouvrir <http://127.0.0.1:8000/docs> pour Swagger et
<http://127.0.0.1:8000/openapi.json> pour le schéma. Attendre le message
`Application startup complete`. Le démarrage charge et contrôle les quinze
modèles sur CPU. Les imports scientifiques utilisent le projet installé dans
le venv, avec ses versions existantes de torch, torchvision, NumPy,
scikit-learn et des outils d'évaluation. Les versions HTTP testées sont
figées dans `backend/requirements.txt`.

| Méthode | Endpoint | Utilisation |
| --- | --- | --- |
| GET | `/health` | État du service, CPU, nombre de modèles disponibles |
| GET | `/model/metadata` | Versions SHA256, seuils, prétraitements, environnements et indisponibilités |
| POST | `/predict` | Décision et score pour une image |
| POST | `/predict/visualize` | Même prédiction avec image, heatmap et overlay PNG en base64 |

`GET /model/metadata` accepte les filtres facultatifs `model` et `category`.
Les POST exigent les trois champs multipart `file`, `model`, `category`.
Les valeurs autorisées sont `B0`, `A1`, `T0`, `T1`, `T2` et `bottle`,
`hazelnut`, `leather`. Dans Swagger, développer le POST choisi, cliquer
sur **Try it out**, renseigner les deux valeurs, sélectionner une image PNG
ou JPEG et cliquer sur **Execute**.

Pour vérifier les GET depuis un second terminal PowerShell, exécuter

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod "http://127.0.0.1:8000/model/metadata?model=T1&category=bottle"
```

Créer une image synthétique temporaire puis tester les POST avec `curl.exe`.

```powershell
$sample = Join-Path $env:TEMP "resilientinspect-api-sample.png"
& .\.venv\Scripts\python.exe -c "import sys; from PIL import Image; Image.new('RGB', (173, 89), (61, 110, 170)).save(sys.argv[1])" $sample
curl.exe --fail-with-body -X POST http://127.0.0.1:8000/predict -F "model=B0" -F "category=bottle" -F "file=@$sample"
curl.exe --fail-with-body -X POST http://127.0.0.1:8000/predict/visualize -F "model=T1" -F "category=bottle" -F "file=@$sample"
```

Les réponses contiennent `category`, `model`, `version`, `anomaly_score`,
`threshold`, `decision`, `inference_time_ms`, `request_id`. La version est
le SHA256 complet du checkpoint. La décision applique strictement
`score > threshold`. Le temps d'inférence couvre le forward, le calcul du
score et, pour la visualisation, Grad-CAM. Le décodage, le prétraitement,
l'attente du verrou et l'encodage des PNG se trouvent en dehors de cette mesure.
Chaque réponse porte aussi l'en-tête `X-Request-ID`.

Pour enregistrer les trois PNG retournés par la visualisation, utiliser

```powershell
$jsonPath = Join-Path $env:TEMP "resilientinspect-visualization.json"
curl.exe --fail-with-body -sS -X POST http://127.0.0.1:8000/predict/visualize -F "model=B0" -F "category=bottle" -F "file=@$sample" -o $jsonPath
$result = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json
foreach ($name in @("image", "heatmap", "overlay")) {
    $property = "${name}_png_base64"
    $destination = Join-Path $env:TEMP "resilientinspect-$name.png"
    [IO.File]::WriteAllBytes($destination, [Convert]::FromBase64String($result.visualization.$property))
}
```

## Chargement et calculs

Les chemins sont résolus depuis le dépôt contenant le code. Les modèles sont
chargés une fois au démarrage en mode eval, gradients des paramètres gelés,
avec deux threads CPU et les réglages déterministes existants. Chaque couple
modèle/catégorie possède son instance et son verrou. Ce verrou protège
également les requêtes ordinaires pendant les hooks temporaires Grad-CAM.

B0/A1 réutilisent les découvreurs et chargeurs stricts existants. Seuls les
runs canoniques `full_*`, terminés, sélectionnés sur validation, sont admis.
Les calibrations sont lues sous
`reports/evaluation/<b0|a1>/<SHA_protocole_12>/<catégorie>/` et contrôlées
par leur SHA et leur liaison au checkpoint, au manifeste et au code. Le
prétraitement appelle `letterbox_pair`, RGB [0,1], 256×256. Le score utilise
`anomaly_maps` puis `image_score`, moyenne des 1 % de pixels d'erreur RGB L1
les plus élevés parmi les pixels valides, avec exclusion du padding.

T0/T1/T2 utilisent l'unique run `full_*` seed42 de chaque catégorie et
`inspect_run`. Le rapport CPU `compatibility.json` doit être présent sous
`reports/transfer/portability/`, avoir son SHA enregistré dans
`validation_summary.json`, porter un succès et correspondre aux mêmes poids,
seuil, manifeste, sources, protocole, code et environnement CPU courant.
Le score réutilise la normalisation ImageNet puis `sigmoid(logit)`.
Les checkpoints, calibrations et résultats sont utilisés en lecture seule.
Le démarrage lit le manifeste comme métadonnées, sans construire de Dataset.

Les visualisations partagent les coordonnées du letterbox 256×256, avec
padding noir. La réponse fournit les dimensions originales et le padding
pour permettre au client de retrouver la zone utile. La heatmap B0/A1
représente l'erreur L1 sur une échelle absolue [0,1], du bleu au rouge.
L'opacité de l'overlay augmente avec l'intensité de la carte.
Grad-CAM appelle la fonction existante sur le logit anomalie, avec une
échelle relative par image. Son champ `is_segmentation` vaut `false`.

## Entrées et erreurs

Les fichiers PNG/JPEG fixes sont limités à 10 Mio et 20 millions de pixels.
L'extension doit correspondre au format réellement décodé. Les modes couleur
sont convertis en RGB selon le prétraitement existant. Les dimensions sont
contrôlées avant décodage complet. Le corps multipart est borné à 10 Mio
plus 64 Kio avant son analyse, y compris sans `Content-Length`.
Les uploads restent temporaires et les visualisations sont renvoyées en mémoire.

Les erreurs renvoient un objet `code`, `message`, `request_id`.

| Statut | Situation |
| --- | --- |
| 400 | Image vide, corrompue ou multipart invalide |
| 413 | Limite de fichier, de requête ou de pixels dépassée |
| 415 | Extension, format ou animation refusé |
| 422 | Catégorie, modèle ou champ obligatoire invalide |
| 503 | Modèle ou artefact de validation absent, ambigu ou invalide |
| 500 | Échec du calcul d'inférence ou de visualisation |

`/health` renvoie 503 et `degraded` si les quinze modèles ne sont pas tous
prêts. `/model/metadata` expose alors les couples indisponibles. Les détails
techniques des erreurs sont journalisés côté serveur, avec l'identifiant de
requête pour les erreurs d'inférence.

## Vérifications et périmètre du MVP

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_backend_api.py -q -W error --tb=short
& .\.venv\Scripts\python.exe -m pytest -q -W error --tb=short
& .\.venv\Scripts\python.exe -m pip check
```

Les tests TestClient emploient des images et modèles temporaires synthétiques,
ainsi que des fixtures full fabriquées sans entraînement pour vérifier les
chargeurs. Ils couvrent les quinze combinaisons, le score et prétraitement
exacts, les visualisations, les SHA altérés, l'exclusion des smoke, les limites
d'upload et les appels concurrents. Les tests se trouvent dans
`tests/test_backend_api.py`, intégré à la découverte pytest du dépôt.

La vérification locale du 17 novembre 2026 obtient 46 tests API réussis et
558 tests réussis sur la suite complète, avec deux anciens tests CUDA ignorés.
Les deux endpoints de prédiction ont aussi été exercés sur les quinze vrais
checkpoints avec une image synthétique temporaire, soit trente réponses 200.
Chaque score est identique au calcul direct du module scientifique. Les
quinze états de modèles sont préservés après ces appels. Uvicorn a été testé
sur localhost avec les routes de santé, métadonnées, Swagger et prédiction,
puis arrêté. `pip check` réussit.

Le rapport `reports/experiments/backend_api_verification.json` conserve les
preuves. Les 970 fichiers présents dans l'inventaire initial sont identiques
en SHA256, taille et date. Six fichiers de résultats T2 supplémentaires sont
apparus pendant la vérification, avec une origine non vérifiée. Ils sont
consignés comme ajouts à l'inventaire. Le service utilise les artefacts en
lecture seule. La vérification des trente prédictions a interdit toute
lecture sous `data/raw` au moyen de gardes sur les ouvertures de fichiers.

Le service cible l'usage local CPU et la seed42 du transfert. L'appelant
renseigne la catégorie. Les visualisations sont rendues en 256×256. Une
instance conserve les quinze modèles en mémoire. L'authentification et
l'exposition réseau publique nécessiteront une étape dédiée. Un nouvel
environnement scientifique exige des artefacts de validation compatibles.

Les sources du service sont réparties entre `main.py` pour les routes et
erreurs HTTP, `models.py` pour les artefacts, `inference.py` pour les appels
scientifiques, `imaging.py` pour les uploads et PNG, `schemas.py` pour les
contrats, `middleware.py` pour la limite HTTP et les identifiants, `config.py`
pour les chemins et limites et `errors.py` pour les erreurs publiques.

Références d'implémentation pour le multipart et le cycle de chargement des
modèles, dans la documentation officielle
[FastAPI Forms and Files](https://fastapi.tiangolo.com/tutorial/request-forms-and-files/)
et [FastAPI Lifespan](https://fastapi.tiangolo.com/advanced/events/).
