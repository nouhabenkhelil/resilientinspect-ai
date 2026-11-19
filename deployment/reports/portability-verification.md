# Vérification de la reprise Docker — 19 novembre 2026

Résultat : Docker Linux opérationnel, 15/15 checkpoints full chargés sur CPU, services backend/frontend healthy sur les ports 8001/18080. Les archives scientifiques et le lancement Windows sont préservés.

## Tests obligatoires

| Contrôle | Résultat observé |
| --- | --- |
| A à docker compose config --quiet | Code 0 |
| B à docker compose up --build -d --wait --wait-timeout 240 | Code 0, les deux services healthy |
| C à GET /api/health | HTTP 200, status=ok, ready_models=15 |
| D à GET /api/model/metadata | HTTP 200, 15 modèles, aucune indisponibilité |
| E/F à POST /api/predict | HTTP 200 pour les 15 couples famille/catégorie, dont B0 et T2 |
| G à POST /api/predict/visualize | HTTP 200 pour les 15 couples ; 3 PNG 256×256 vérifiés par réponse |
| H à parité Windows/Linux | 850 comparaisons réussies selon la politique préalable ; 5 décisions limites détaillées ci-dessous |
| I à accès React/Nginx | HTML React, ressources JS/CSS et proxy /api vérifiés par HTTP ; parcours visuel navigateur non validé |
| J à régressions | 60 tests backend/Docker/portabilité + 201 tests scientifiques + 36 tests frontend réussis |

La vérification visuelle a été interrompue par Computer Use : il ne pouvait pas déterminer avec assez de certitude l’URL de Chrome sous Windows pour appliquer sa politique. Aucun clic de prédiction dans React n’est revendiqué. Le chargement React et le proxy sont prouvés par HTTP et les interactions React par ses tests unitaires ; la vérification manuelle du navigateur reste à faire à http://localhost:18080.

## Preuves et portée

- [Rapport HTTP réel](container-portability-integration.json) : 30 POST valides, 15 prédictions et 15 visualisations. Une vraie image normale val par catégorie, vérifiée par SHA256. Aucun PNG artificiel utilisé comme preuve.
- [Référence Windows](portability/windows.json) et [mesure Linux](portability/linux.json), avec fichiers SHA256 associés.
- [Protocole fixé avant mesure](../PORTABILITY.md) : atol=1e-5, rtol=1e-4 ; basculement admis uniquement si les deux scores sont à moins de 1e-5 du seuil original.
- Tous les fichiers split=val : bottle 42, hazelnut 79, leather 49 ; cinq familles, soit 850 comparaisons. Aucun fichier test utilisé, aucune recalibration.
- Scores Windows B0/A1 identiques aux scores de validation archivés : erreur maximale 0.
- Cette mesure couvre la validation normale disponible ; elle ne mesure pas une performance test ni une invariance sur toutes les entrées futures. Les rapports synthétiques de transfert originaux restent vérifiés par leurs SHA256.

## Mesures par checkpoint

| Modèle | Images | Écart maximal absolu | Décisions changées |
| --- | ---: | ---: | ---: |
| B0/bottle | 42 | 3.407277713e-08 | 1 |
| B0/hazelnut | 79 | 8.342151608e-09 | 0 |
| B0/leather | 49 | 1.174375051e-08 | 0 |
| A1/bottle | 42 | 2.232902661e-08 | 1 |
| A1/hazelnut | 79 | 1.393803736e-07 | 1 |
| A1/leather | 49 | 4.974625462e-09 | 0 |
| T0/bottle | 42 | 5.587935448e-08 | 0 |
| T0/hazelnut | 79 | 5.587935448e-08 | 0 |
| T0/leather | 49 | 2.619344741e-09 | 0 |
| T1/bottle | 42 | 4.917383194e-07 | 0 |
| T1/hazelnut | 79 | 1.192092896e-06 | 0 |
| T1/leather | 49 | 1.098960638e-07 | 1 |
| T2/bottle | 42 | 1.89174898e-09 | 0 |
| T2/hazelnut | 79 | 8.80099833e-08 | 0 |
| T2/leather | 49 | 1.571606845e-08 | 1 |

## Cinq décisions au voisinage du seuil

Les comparaisons appliquent toujours `score > seuil`, sans arrondi ni marge ajoutée. Aucun seuil n’a changé. Toutes les différences ci-dessous respectent la règle préalable.

| Modèle / image | Score Windows | Score Linux | Seuil original |
| --- | ---: | ---: | ---: |
| B0/bottle à bottle/train/good/182.png | 0.20367741357625985 | 0.20367744442348074 | 0.20367741357625985 |
| A1/bottle à bottle/train/good/124.png | 0.14375584244319214 | 0.14375586317079822 | 0.14375584244319214 |
| A1/hazelnut à hazelnut/train/good/310.png | 0.27611515548352789 | 0.27611517111157496 | 0.27611515548352789 |
| T1/leather à leather/train/good/200.png | 0.013787147589027882 | 0.013787056319415569 | 0.013787128962576389 |
| T2/leather à leather/train/good/164.png | 0.00068825017660856247 | 0.00068824324989691377 | 0.00068824691697955132 |

## Intégrité et isolation

`prepare_compose.py --check` confirme les 273 entrées scientifiques inchangées avant et après les mesures. Le service normal possède 274 bind mounts en lecture seule (273 fichiers + dossier de preuves), aucun bind en écriture et aucune image dataset montée. L’override hors ligne monte uniquement les 170 images val autorisées en lecture seule et écrit les nouvelles preuves sous /evidence. Il n’est pas utilisé pour le service.

Inspection de /app dans l’image backend : aucun .pt/.pth/.ckpt, image dataset ou .env. PyTorch 2.15.0+cpu et torch.version.cuda=None ; utilisateurs inspector/nginx. Le frontend est construit avec Vite, puis servi par Nginx. Le port 8080 et Oracle ne sont pas modifiés.

Les anciens rapports de première conteneurisation sont conservés : [historique](verification.md) et container-integration.json. Les anciens blocages présents dans input-inventory.json décrivent les contraintes des archives avant adaptation ; les nouvelles preuves ci-dessus documentent leur résolution.

## Fichiers de la reprise

- Modifié : backend/app/models.py (résolution portable et admission par preuve).
- Créés : backend/app/portability.py, deployment/validate_portability.py, deployment/PORTABILITY.md, scripts/prepare_validation.py, deployment/docker-compose.validation.yml, tests/test_deployment_portability.py.
- Mis à jour parmi les fichiers Docker déjà présents non suivis : backend/Dockerfile, .dockerignore, docker-compose.yml (preuve en lecture seule et défaut 18080), deployment/.env.example, deployment/README.md, scripts/check_containers.py, tests/test_compose_deployment.py.
- Preuves nouvelles : deployment/reports/portability/windows.json et linux.json avec SHA256, container-portability-integration.json et six PNG dans visualizations/.
- Historique préservé : deployment/reports/verification.md, annoté avec un lien vers ce rapport.
- Conservés : frontend/Dockerfile, frontend/nginx.conf, frontend/.dockerignore, backend/requirements-cpu.txt, docker-compose.mounts.yml, scripts/prepare_compose.py et les autres fichiers préexistants.
- Aucun fichier sous src/, checkpoint, configuration scientifique, calibration, manifeste ou résultat officiel modifié. Pas de commit créé ; les modifications initialement non suivies restent présentes.

## Commandes PowerShell

```powershell
$env:RI_FRONTEND_PORT = '18080'
docker compose up --build -d --wait --wait-timeout 240
Invoke-RestMethod http://localhost:18080/api/health
# Arrêt :
docker compose down
```

La procédure complète de reproduction et le lancement de secours Windows sont dans [deployment/README.md](../README.md). Les preuves doivent être renouvelées après changement des sources ou du runtime contrôlés. Les conteneurs sont laissés démarrés pour la démonstration.
