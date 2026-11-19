# Historique de la première conteneurisation

Ce rapport décrit les essais antérieurs à l’adaptateur. Pour la reprise et les mesures actuelles, consulter [portability-verification.md](portability-verification.md). Les échecs ci-dessous restent conservés comme historique.

# Vérification Docker Compose — 17 novembre 2026

**Résultat : images construites et routage HTTP vérifié ; système d’inférence
Linux non validé. Aucune prédiction Docker réussie n’est revendiquée.**

La cible reste la validation du 24 novembre 2026. Les deux problèmes restants
sont la portabilité des preuves scientifiques Windows vers Linux et l’occupation
du port 8080 sur le PC. Le lancement local Windows existant est conservé.

## Fichiers livrés

| Fichier | Rôle |
| --- | --- |
| `backend/Dockerfile` | Image d’inférence CPU, utilisateur non root et healthcheck |
| `backend/requirements-cpu.txt` | Versions de service et dépendances scientifiques CPU |
| `frontend/Dockerfile` | Build Node/Vite puis image finale Nginx |
| `frontend/nginx.conf` | SPA, statiques, `/api/`, temporaires sous `/tmp` |
| `docker-compose.yml` | Deux services, ports, racines en lecture seule, contrôle de santé |
| `docker-compose.mounts.yml` | 273 montages de fichiers, générés et en lecture seule |
| `.dockerignore`, `frontend/.dockerignore` | Contextes limités aux sources nécessaires |
| `deployment/.env.example` | Chemins et ports configurables |
| `deployment/healthcheck.py` | Readiness stricte de quinze modèles CPU |
| `deployment/__init__.py` | Package des helpers de déploiement |
| `scripts/prepare_compose.py` | Génération du plan et contrôle SHA256 sans copie des entrées |
| `scripts/check_containers.py` | Tests HTTP réels avec image synthétique en mémoire |
| `tests/test_compose_deployment.py` | Tests des montages, exclusions et disponibilité |
| `deployment/README.md` | Lancement Windows, architecture, configuration et limites |
| `deployment/reports/input-inventory.json` | Tailles et SHA256 des entrées montées |
| `deployment/reports/container-integration.json` | Réponses HTTP et échecs réels |
| `deployment/reports/images.json` | Identifiants et tailles des images finales |
| `deployment/reports/verification.md` | Présent rapport |

Les sources `backend/app/`, `src/`, `pyproject.toml`, les configurations, le
frontend React/Vite local et les artefacts officiels n’ont pas été modifiés.
Le fichier `package-lock.json` non suivi déjà présent à la racine n’a pas été utilisé.

## Tests réellement exécutés

| Vérification | Résultat observé |
| --- | --- |
| Docker CLI / Compose | Docker 29.8.0, Compose v5.5.1 ; moteur Linux démarré via Docker Desktop |
| `docker compose config --quiet` | Valide |
| Génération du plan | 273 fichiers, dont 15 checkpoints ; aucun contenu copié |
| `pytest tests/test_compose_deployment.py tests/test_backend_api.py -q -W error --tb=short` | **57 réussis**, dont 11 nouveaux tests de déploiement et 46 tests API existants |
| `npm.cmd --prefix frontend test` | **36 réussis**, 3 fichiers de tests |
| Build frontend dans Docker | TypeScript strict et Vite réussis ; image Nginx construite |
| Build backend dans Docker | Installation CPU, `pip check`, imports et contrôle des versions réussis |
| Dépendances GPU | `torch.version.cuda` vaut `None` ; aucun paquet NVIDIA/CUDA/Triton installé |
| `PROJECT` du code scientifique | `/app`, testé au build avec l’installation editable |
| Image backend sans volumes | Aucun checkpoint `.pt`, image raster `.png` ou répertoire de données sous `/app` |
| Montages en cours d’exécution | **273 fichiers réguliers, SHA256 exacts et 273 bind mounts avec `RW=false`** |
| `prepare_compose.py --check` | **273 entrées inchangées**, aucune écriture |
| `docker compose up -d --wait --wait-timeout 30` | **Échec de disponibilité** : attente des quinze modèles non satisfaite ; frontend retenu par la dépendance |
| `nginx -t` dans le conteneur final | Configuration valide |
| Santé Nginx | HTTP **200**, service sain sur le port diagnostic 18080 |
| HTML React | HTTP **200** via Nginx |
| Métadonnées FastAPI directes et via `/api` | HTTP **200**, listes cohérentes : 0 modèle prêt, 15 indisponibles |
| Santé FastAPI directe et via `/api` | HTTP **503**, `degraded`, **0/15** modèles prêts |
| POST réels `/api/predict` et `/api/predict/visualize`, B0/bottle | HTTP **503**, `model_unavailable`, identifiants réels dans le rapport JSON |
| POST d’un fichier `.gif` invalide via Nginx | HTTP **415**, erreur FastAPI transmise |
| `scripts/check_containers.py` | **Échec attendu et conservé**, car aucune inférence n’est admissible sous Linux |

Le diagnostic Nginx a utilisé `RI_FRONTEND_PORT=18080` et
`docker compose up -d --no-deps frontend`, uniquement après constat de l’échec
de disponibilité. Cela a permis de tester le routage contre le vrai backend
dégradé. Le fichier Compose livré conserve `condition: service_healthy` ;
`--no-deps` n’est pas présenté comme un lancement normal validé.

Le test d’intégration génère son PNG RGB 173 × 89 en mémoire. Il ne lit aucune
image MVTec et n’optimise aucun seuil. Les fixtures des tests unitaires restent
des données de test et ne servent jamais de réponse dans l’application.

## Blocages confirmés

**Portabilité scientifique.** Les six calibrations AE contiennent des chemins
de checkpoints Windows absolus comparés strictement aux chemins découverts.
Les neuf rapports CPU du transfert sont liés exactement à l’environnement
Windows de leur validation. Le runtime Linux conserve les versions de Python,
Torch, Torchvision, NumPy, scikit-learn et Pillow, mais ne peut pas fournir ces
chemins ou cette plateforme Windows. Les journaux du chargeur confirment les
refus de calibration AE et de validation CPU du transfert. Le healthcheck
reste donc en échec. Les scores et seuils officiels ne sont pas modifiés pour
forcer un démarrage.

**Port demandé.** Le processus `TNSLSNR` (listener Oracle) écoute déjà sur
8080. Un essai de publication Docker sur 127.0.0.1:8080 a été refusé par Windows.
Oracle n’a pas été arrêté et aucun réglage réseau ou de sécurité n’a changé.
Le défaut du projet reste 8080 ; les tests ont utilisé le port alternatif 18080.

## Corrections effectuées pendant les essais

Les chemins relatifs d’un fichier Compose utilisé par `extends` étaient résolus
depuis le répertoire de ce fichier. Le fragment généré a été placé à la racine,
à côté de `docker-compose.yml`, pour rendre les chemins conformes au dépôt.
Les seuls répertoires vides créés par ce premier essai sous `deployment/` ont
été contrôlés puis supprimés ; aucun fichier scientifique n’y était présent.
La validation finale compare les SHA256 des 273 fichiers réellement montés.

Nginx initialise aussi les répertoires FastCGI/uWSGI/SCGI, même sans route qui
les utilise. Ils sont explicitement placés sous `/tmp` pour permettre le
démarrage non root avec la racine en lecture seule. Le test réel `nginx -t`
et le HTTP 200 ont été obtenus après cette correction.

Le cache pip est monté au chemin effectif associé à `HOME=/tmp`, afin que les
roues téléchargées restent dans le cache BuildKit et ne soient pas livrées dans
l’image. Les dépendances restent séparées des sources pour réutiliser leur
couche lors des changements applicatifs.

## Limites et arrêt de mission

Il reste à concevoir et valider la portabilité Linux des chemins et des preuves
de compatibilité, en conservant les poids, les calibrations et les seuils
officiels. Une réussite sur une seule image synthétique ne remplacerait pas
cette validation. La compatibilité Linux des quinze modèles, leurs scores et
les visualisations n’est donc **pas** déclarée acquise.

La revue visuelle dans un navigateur et une démonstration complète d’inférence
Docker ne sont pas validées ici. Les tests HTTP vérifient la livraison des
fichiers et le routage, pas le rendu visuel.

Après collecte des preuves, les conteneurs et le réseau de test sont arrêtés
et retirés avec `docker compose down`. Les images construites restent locales
pour revue. Aucune suppression globale d’images ou de caches n’est effectuée.
Les autres services du PC sont conservés.

**Arrêt avant DVC et MLflow Registry.**
