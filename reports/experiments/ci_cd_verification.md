# Vérification finale CI/CD — 20 novembre 2026

Les deux workflows demandés sont implémentés et **validés localement**.
**Aucune exécution GitHub Actions n’a été vérifiée à ce stade.** La mission
s’arrête avant commit/push manuel et vérification des runs distants. Aucun
déploiement ou envoi d’image vers un registre n’est automatisé.

## Workflows livrés

| Fichier | Jobs | Validation |
|---|---|---|
| [ci-tests.yml](../../.github/workflows/ci-tests.yml) | Intégrité/lint Python, tests CPU, frontend | actionlint réussi, commandes exécutées localement |
| [docker-build.yml](../../.github/workflows/docker-build.yml) | Matrice backend/frontend | Deux images construites, Dockerfiles et Compose de build contrôlés |

Déclencheurs : push sur `main`, pull request, `workflow_dispatch`. Runners
Ubuntu 22.04, permissions limitées à `contents: read`, checkout sans credentials
persistants, timeouts et annulation des runs obsolètes sur la même branche/PR.
Pas de `pull_request_target`, secret requis, `dvc pull` hébergé ou publication
d’artefact scientifique.

Actions officielles vérifiées auprès de leurs dépôts et fixées par SHA complet :

| Action | Version | Commit |
|---|---|---|
| actions/checkout | 7.0.1 | 3d3c42e5aac5ba805825da76410c181273ba90b1 |
| actions/setup-python | 7.1.0 | 6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 |
| actions/setup-node | 7.1.0 | 949feb2413d6458794dcd2491c4babbbce0c15c1 |

Python 3.11.9, Node 22.22.1 et dépendances CPU existantes sont conservés.
Le verrou Linux dédié a été extrait de l’environnement réellement testé ;
les versions communes correspondent à l’environnement d’outillage local. La
dépendance conditionnelle `gunicorn` est installée uniquement sous Linux.
`pip check` réussit dans l’environnement Linux.

## Résultats locaux réellement exécutés

| Contrôle | Résultat |
|---|---|
| Suite Python Linux sans réseau et sans données/checkpoints officiels | **603 passed, 3 skipped**, zéro échec, 606 cas collectés |
| Skips Linux | Un bootstrap PowerShell Windows ; deux tests CUDA, conformément aux conditions existantes |
| Tests Vitest | **70 réussis**, 11 fichiers, avec `npm ci` et Node 22.22.1 |
| Sources des agrégats officiels, parcours local | **4 tests réussis** ; quinze sources/agrégats authentifiés |
| Ruff 0.17.6 | E9/F63/F7/F82 réussis sur les chemins Python annoncés |
| ESLint 10.15.0 | Réussi, zéro avertissement avec la politique explicite du projet |
| TypeScript 7 | `tsc --noEmit` réussi |
| Contrats FastAPI/TypeScript | Snapshot dérivé du vrai OpenAPI, six réponses et deux contrats multipart conformes |
| Données scientifiques publiques | Quinze combinaisons et six agrégats de benchmark cohérents, sans inventer de sources absentes du runner |
| Build Vite Windows et image frontend Linux | Réussis ; assets identiques à l’application existante |
| Syntaxe YAML/actions | actionlint 1.7.12 réussi ; archive officielle contrôlée par SHA256 |
| Syntaxe PowerShell du parcours local | ParseFile réussi et script intégral exécuté |
| Métadonnées DVC | Deux pointeurs lisibles, 1 898 références cohérentes, 15 checkpoints full et 14 graphes admis |
| Garde Git | Aucun poids, donnée, base SQLite, cache, secret au format contrôlé ou fichier >5 Mio dans les candidats restants |

La suite Linux a été exécutée dans un conteneur local construit à partir d’un
checkout de candidats Git dépourvu des données originales, poids, caches DVC et
store MLflow. Les tests fabriquent leurs fichiers temporaires synthétiques,
notamment de petits graphes ONNX et des entraînements miniatures de fixtures.
Les quinze modèles scientifiques ne sont pas réentraînés ni réexportés.
Ce conteneur Debian/WSL2 n’est pas une exécution sur le runner GitHub Ubuntu ;
la première exécution distante reste nécessaire.

Un avertissement MLflow non bloquant signale l’absence d’annotations de types
dans le wrapper Registry existant. Il est conservé ; modifier ce wrapper
changerait son conditionnement sans nécessité pour cette mission.

## Corrections de tests pour Linux

Deux problèmes de portée des tests ont été corrigés **hors des sources protégées** :

- Le test de refus ONNX choisit la preuve `parity-linux.json` ou
  `parity-windows.json` correspondant réellement au runtime, au lieu d’imposer Windows.
- Le test des chargeurs scientifiques vérifie leurs fixtures directement ; un
  test distinct vérifie que le démarrage Linux refuse ces fixtures lorsqu’elles
  n’ont pas de preuve de déploiement. Aucun contrôle d’admission n’est neutralisé.

Les contrôles SHA256, calibrations, tolérances numériques et code de production
ne sont pas modifiés. La suite complète a été relancée après ces corrections.

## Politique de lint et contrats

Le dépôt ne prétend pas respecter un formatage ou un ensemble complet de règles
PEP8/ESLint recommended. Ruff couvre les erreurs critiques explicitement choisies.
L’audit plus large E4/E7/E9/F a relevé 227 diagnostics de style/imports/fixtures
réutilisées, conservés sans réécriture massive des modules historiques.

ESLint utilise Babel 8.1.2 pour analyser les fichiers TS/TSX et scripts JS/MJS,
avec neuf règles de correction explicites. TypeScript 7 strict vérifie les types.
Le parseur typescript-eslint 8.73.0 refuse TypeScript 7 dans ses peer dependencies ;
aucun `--force`, changement de version TypeScript ou contournement npm n’est utilisé.
React Bits reste exclu du lint de style et conserve ses licences et son code.

Les contrats OpenAPI sont contrôlés contre FastAPI sans démarrer son lifespan.
Les scripts frontend vérifient les interfaces et les agrégats réels versionnés.
L’authenticité des sources scientifiques absentes du runner est contrôlée dans
le parcours local, pas présentée comme prouvée par la CI hébergée.

## Images Docker construites

Les Dockerfiles et le Compose de production sont inchangés. La configuration
temporaire CI réutilise uniquement leurs définitions de build, sans montages de
modèles, `extends`, ports ou dépendances de service. Les images de base sont
fixées par digest dans [images.json](../../scripts/ci/images.json).

| Image locale CI | Identité locale observée | Contrôle |
|---|---|---|
| resilientinspect-ci-backend:local | sha256:e63aa38adbb647c361553d0ef80688dc3cfbc4f52f956baea2c01d84221aac6f | Build CPU/ORT, import, absence de données/poids, sans réseau |
| resilientinspect-ci-frontend:local | sha256:b78a35344152739f8147fb92ca65cb82ecf4ebb81be7f92d3106c80ae3e13604 | Build Vite et `nginx -t`, sans serveur backend |

Les deux Dockerfiles passent `docker build --check` sans avertissement.
Ces images ne sont pas publiées. Les builds CI ne revendiquent aucun modèle
scientifique chargé. Les véritables admissions restent celles de l’application
locale avec les artefacts.

## Parcours local intégral avec artefacts

`scripts/ci/validate-local.ps1` a réellement terminé ses **13 étapes** et vérifié
les deux conteneurs déjà en cours, sans les recréer ou les arrêter :

- 1 898 fichiers de livraison DVC contrôlés par SHA256 ; workspace à jour et
  remote local synchronisé. Aucun `dvc push/pull` supplémentaire nécessaire.
- Historiques MLflow authentiques inchangés ; trois versions T2 et leurs alias
  chargés par URI. Comparaison sur **170 images normales val**, écart maximal
  de score **0**, sans changement de seuil.
- 273 fichiers scientifiques du plan Docker inchangés ; empreintes des sources
  compatibles avec les preuves PyTorch et ONNX existantes.
- Huit POST FastAPI réels réussis : B0/T2 × PyTorch/ONNX × predict/visualize.
  Moteur invalide : **422** ; T1/bottle ONNX : **503**, sans repli silencieux.
- Chromium : **24 layouts** (desktop/laptop/mobile, deux thèmes, quatre pages),
  comparaison et historique réels ; parcours ONNX ; cinq écrans MLflow avec
  métriques, paramètres, artefacts, versions et alias. Contrôles navigateur réussis.
- Disponibilité finale : **15 modèles PyTorch et 14 modèles ONNX**.
- Vérification des quinze agrégats contre leurs sources officielles et quatre
  tests d’archives réussis.

Les SHA256 des **quinze graphes ONNX originaux** ont également été vérifiés,
y compris le graphe T1/bottle volontairement refusé. Aucun export, benchmark ou
recalcul des preuves scientifiques de portabilité n’a été lancé. Les copies de
livraison DVC et les originaux sont conservés.

| Service | État final | Accès/identité |
|---|---|---|
| Backend de service | running / healthy | 502d83809831, 127.0.0.1:8001 |
| Frontend de service | running / healthy | aa30d70c36dc, http://localhost:18080 |
| MLflow | HTTP 200, indépendant de FastAPI | http://127.0.0.1:5000 |
| Oracle TNSLSNR | Toujours en écoute | PID 5216, port 8080 |

Les conteneurs de service conservent leurs identifiants. Les assets frontend
restent `index-bos9nale.js`, `index-D2Scaee6.css` et `Analytics-GvpFm8DG.js`.
Le frontend 2.0 et son identité DESIGN.md ne sont pas modifiés.

## Anomalie historique et exclusion Git

L’audit a trouvé **13 615 fichiers d’environnement `.mlflow-ui` déjà suivis**
depuis le commit `d27569d9d0e25659252b33a204007377920ceec6`. Six blobs dépassent
5 Mio, pour **92 390 400 octets** cumulés. Ce sont des bibliothèques de
l’environnement, pas les checkpoints scientifiques.

Ils sont retirés **uniquement de l’index**, par `git rm --cached` : tous les
fichiers physiques restent disponibles et MLflow demeure actif. L’historique
Git n’est ni supprimé ni réécrit ; les anciens blobs restent présents. Aucun
nettoyage distant ou force-push n’est effectué. Le contrôle CI bloque leur
réintroduction dans l’arbre courant. L’audit ne certifie pas tout l’historique
exempt de secrets.

Détails : [ci_cd_history_audit.json](ci_cd_history_audit.json).
Les métadonnées et rapports légitimes restent autorisés. Les images MVTec
connues sont détectées par empreinte, les SQLite par signature et les checkpoints
Torch ZIP par structure, même après renommage ; des tests négatifs vérifient ces
contrôles. Aucun fichier candidat restant ne dépasse 5 Mio.

## Commandes, publication et limites

Commandes exactes et classification :
[guide CI](../../scripts/ci/README.md), [README principal](../../README.md).
Résumé machine : [ci_cd_verification.json](ci_cd_verification.json).
Liste exacte à publier, **incluant les retraits de suivi de l’environnement** :
[ci_cd_publish_files.txt](ci_cd_publish_files.txt).

Après publication manuelle, ouvrir les deux pages GitHub Actions, constater le
commit testé, les jobs et les logs. Les badges seuls ne prouvent pas le succès.
Aucun résultat distant au vert n’est annoncé ici.

Limites : dépendances externes/runners et mises à jour APT ne garantissent pas
des images bit-identiques ; les trois skips ne valident pas CUDA ou PowerShell
sous Linux. Le remote DVC et SQLite MLflow sont locaux, sans sauvegarde hors
machine. Une autre machine doit posséder les artefacts, octets de source et
runtimes compatibles. Les anciens gros blobs restent dans l’historique.
T1/bottle ONNX reste refusé et la sélection T2 demeure rétrospective.

Aucune modification de poids, seuil, calibration ou résultat officiel. Aucun
commit/push automatique, publication de modèle, nouveau frontend ou rapport
LaTeX n’est réalisé. La phase s’arrête après la validation locale demandée.
