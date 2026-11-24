# Validation CI/CD

Deux workflows GitHub Actions, sans entraînement officiel, récupération DVC
distante, publication d’image ou déploiement automatique. L’activation et les
résultats distants restent à constater après le commit/push manuel de l’utilisateur.

## Parcours hébergé

`ci-tests.yml` exécute trois jobs indépendants sur Ubuntu 22.04 :

- **Repository** : fichiers candidats Git, métadonnées DVC, actionlint et Ruff.
- **Backend** : Python 3.11.9, roues CPU PyTorch 2.15.0 / Torchvision 0.29.2,
  ONNX 1.23.2, ORT 1.32.0, dépendances MLflow nécessaires aux fixtures ;
  `pip check`, vérification CPU, contrat OpenAPI et tests Python.
- **Frontend** : Node 22.22.1, `npm ci`, TypeScript strict, ESLint, contrats
  TypeScript/FastAPI, cohérence des exports scientifiques réels, Vitest et Vite.

`docker-build.yml` construit backend et frontend en matrice. Le script
`docker_build.py` lit les définitions `build` du Compose local, vérifie qu’elles
correspondent au contrat attendu, puis produit un fichier de **build seul**.
Ce fichier n’a ni `extends`, montages, ports, dépendances de runtime ou données.
Les Dockerfiles de service et le Compose de production ne sont pas modifiés.

Docker `build --check` valide les Dockerfiles ; les deux images sont réellement
construites. Le backend est importé dans un conteneur sans réseau et sans
`/app/data` ni `/app/artifacts`. Nginx passe `-t`, avec une entrée locale `backend`
pour résoudre la directive upstream, sans service FastAPI simulé. Ces contrôles
ne prétendent charger aucun des modèles scientifiques.

Les actions officielles sont fixées par SHA complet : checkout **7.0.1**,
setup-python **7.1.0**, setup-node **7.1.0**, avec runtime d’action Node 24.
Les versions ont été vérifiées dans leurs dépôts officiels. Permissions
`contents: read`, checkout sans identifiants persistants, aucun secret requis,
timeouts 10/30/15 minutes pour les jobs tests et 35 minutes pour chaque build.
Les exécutions obsolètes d’un même workflow/branche ou PR sont annulées.

Les dépendances directes réutilisent les fichiers existants. Les contraintes
Windows MLOps existantes restent intactes ; `constraints-linux.txt` ajoute les
versions exactes réellement installées dans le conteneur Linux de vérification,
y compris les dépendances conditionnelles Linux. Les images Python, Node et
Nginx sont fixées par digest dans `images.json`, via les arguments déjà prévus
dans les Dockerfiles. Aucun changement de `pyproject.toml`.

## Classification des tests

| Ensemble | Données nécessaires | Signification |
|---|---|---|
| `tests/` | Configurations Git et fichiers temporaires synthétiques | Prétraitement, architectures, scores, métriques, entraînement miniature de fixtures, FastAPI, erreurs, ONNX, portabilité et packaging |
| `mlops/tests/` | Octets temporaires synthétiques | Refus de corruption SHA256, protection des originaux, sécurité des chemins et remote hors dépôt |
| `scripts/ci/tests/` | Octets synthétiques et configuration Compose | Contrôles négatifs du garde Git et absence de montages de production en CI |
| Vitest `frontend/src/**/*.test.*` | Fixtures API explicitement synthétiques, jsdom | Comportement React et contrat du client ; aucune intégration avec les vrais modèles revendiquée |
| `frontend/scripts/tests/` | Archives officielles locales ignorées par Git | Contrôle des quinze agrégats contre leurs sources authentiques ; parcours local uniquement |
| `check_onnx_api.py`, scripts navigateur, Registry `verify` | Checkpoints full, calibrations, preuves, données val et services locaux | Intégration réelle avec les modèles admis |

Les deux tests CUDA existants restent conditionnels à un GPU ; le test du
bootstrap PowerShell reste conditionnel à Windows. Aucun test indépendant des
artefacts n’est désactivé à cause de l’absence de MVTec ou des checkpoints.
Les petits exports ONNX créés en temporaire sont de vraies opérations ONNX sur
fixtures, jamais une revalidation des quinze graphes scientifiques.

`check_api_contract.py` compare le snapshot technique `api-contract.json` au vrai
`create_app().openapi()`, sans démarrer le lifespan ni charger les poids. Le
frontend analyse l’AST de ses interfaces et compare six réponses complètes,
leurs propriétés/types/enums/héritages et les deux contrats multipart à ce
snapshot. Les propriétés par défaut peuvent rester facultatives côté frontend
pour la compatibilité historique ; `tsc --noEmit` contrôle leur utilisation.
Une modification d’API exige une revue avant `--write` du snapshot technique.
Ce snapshot ne fait pas partie des preuves scientifiques.

`check-public-data.mjs` vérifie les quinze combinaisons, confusion/macro-métriques,
bornes, références SHA256 et les six agrégats de performance réellement archivés.
La CI hébergée vérifie la cohérence des exports versionnés ; elle ne prétend pas
posséder les archives permettant d’authentifier leurs empreintes ou les mesures
brutes. Le parcours local contrôle ces sources.

## Politique de lint

Ruff 0.17.6 applique **E9, F63, F7, F82** à `src`, `backend`, `scripts`, `tests`,
`mlops` et aux scripts Python frontend : syntaxe et erreurs de correction
critiques, dont les noms non définis. Les environnements, copies DVC, données et
caches sont exclus. Aucun `--fix`, Black ou normalisation du code protégé.

Le dépôt conserve des styles historiques à instructions multiples et des imports
de fixtures réutilisées. Un audit plus large E4/E7/E9/F a relevé 227 diagnostics
(notamment E701/E702/F401/F811) ; ce n’est pas le périmètre annoncé comme passant.
La CI n’impose ni formatage, complexité, imports inutilisés ou PEP8 complet.

ESLint 10.15.0 applique neuf règles explicites de contrôle de flux/syntaxe aux
TS/TSX et scripts JS/MJS du frontend. Le code tiers React Bits est exclu du lint
ESLint et conservé avec ses licences. TypeScript 7 reste le vérificateur de types.
Le peer dependency de typescript-eslint/parser 8.73.0 exige TypeScript <6.1 ;
le parseur Babel 8.1.2 permet de conserver TypeScript 7 sans `--force` ni
`--legacy-peer-deps`. Aucune règle du plugin TypeScript ESLint ou du plugin Babel
n’est présentée comme exécutée. Pas de refonte React ou de reformatage général.

## Sécurité des fichiers Git

Le garde inspecte l’index Git ; `--include-untracked` inclut aussi les nouveaux
fichiers candidats locaux. Il ignore les sorties privées déjà ignorées par Git.
Il bloque poids/ONNX/tableaux sérialisés, SQLite (extension ou signature), caches,
données, environnements, `.env` réels, clés et fichiers au-delà de **5 Mio**.
Les images/masques MVTec sont aussi identifiés par leurs SHA256 du manifeste,
même renommés ; les checkpoints Torch ZIP sont reconnus par `data.pkl`.
Les métadonnées `.dvc`, rapports légitimes, marqueurs `.gitkeep`, SVG et
`.env.example` restent autorisés.

Les motifs de secrets ciblent clés privées, AWS et formats de tokens GitHub/OpenAI,
sans afficher leur valeur. Ce contrôle ne certifie pas tout l’historique exempt
de secrets et ne remplace pas la revue du contenu publié.

Anomalie historique constatée : **13 615 fichiers** de l’environnement
`.mlflow-ui` avaient été versionnés dans `d27569d`. Ils sont retirés de l’index
avec `git rm --cached` ; les fichiers locaux, le service MLflow utilisé et
l’historique sont préservés. Six anciens blobs dépassent 5 Mio, soit
92 390 400 octets cumulés. Ils restent dans les commits historiques ; aucun
nettoyage, force-push ou réécriture automatique n’est effectué. Détails dans
[`ci_cd_history_audit.json`](../../reports/experiments/ci_cd_history_audit.json).

## Commandes locales équivalentes

Voir les commandes complètes dans le [README principal](../../README.md).
Pour reproduire les tests hébergés dans un Linux local dépourvu des données :

```powershell
.\.venv-mlops\Scripts\python.exe scripts/ci/docker_build.py --service backend
.\.venv-mlops\Scripts\python.exe scripts/ci/prepare_test_checkout.py
$ciContext = (Get-Content scripts/ci/local/test-checkout.json -Raw | ConvertFrom-Json).path
docker build --file scripts/ci/Dockerfile.tests --tag resilientinspect-ci-tests:local $ciContext
New-Item -ItemType Directory -Path scripts/ci/local/results -Force | Out-Null
docker run --rm --network none --mount "type=bind,source=$((Get-Location).Path)/scripts/ci/local/results,target=/ci-results" resilientinspect-ci-tests:local -m pytest tests mlops/tests scripts/ci/tests -q --tb=short --junitxml=/ci-results/python-linux.xml
docker run --rm --network none resilientinspect-ci-tests:local scripts/ci/check_cpu.py
docker run --rm --network none resilientinspect-ci-tests:local scripts/ci/check_api_contract.py
```

Le script prépare un nouveau contexte contenant uniquement les candidats Git,
sans données, checkpoints, caches, store MLflow ou `node_modules`. Son petit
dépôt Git isolé n’a pas de commit ; cela teste aussi le comportement de diagnostic
sans commit. La suite hébergée travaille avec le vrai checkout GitHub.
Ce conteneur de tests est un outil de vérification, distinct des images de service.

Parcours local avec artefacts restaurés et services déjà démarrés :

```powershell
.\scripts\ci\validate-local.ps1
```

Il contrôle DVC et les SHA256 de livraison, les historiques MLflow, les modèles
du Registry récupérés par URI sur val normale, les deux conteneurs healthy,
les vrais endpoints PyTorch/ONNX et les refus, les navigateurs ONNX/MLflow,
les layouts React multi-formats avec comparaison et historique,
les 15/14 modèles et les sources des agrégats officiels. Il conserve les services,
Oracle et les poids ; aucun export, benchmark, entraînement ou recalcul des
preuves de portabilité n’est lancé. Reçu local dans
`scripts/ci/local/full-validation.json` ; captures et caches sont ignorés par Git.

## Publication et limites

Relire [la liste exacte](../../reports/experiments/ci_cd_publish_files.txt),
incluant le retrait du suivi de l’ancien environnement, puis publier manuellement.
Les workflows ont `push` sur main, `pull_request` et `workflow_dispatch`.
Après publication, ouvrir les deux pages Actions, vérifier le commit exécuté,
les jobs, logs et éventuels skips. Le succès local n’est pas un succès GitHub.
Ne rendre les checks obligatoires en protection de branche qu’après constat
de leur première exécution réelle et de leurs noms.

Les images et dépendances principales sont verrouillées, mais les runners
hébergés, Docker/BuildKit et les mises à jour APT restent externes. Aucun build
bit-identique ou support d’un autre runtime scientifique n’est revendiqué.
Le remote DVC et le Registry sont locaux au PC, sans sauvegarde hors machine ;
une autre machine doit disposer des artefacts et des octets de code/runtime
compatibles. T1/bottle reste refusé avec ONNX et la sélection T2 reste rétrospective.

Références officielles :
[sécurité GitHub Actions](https://docs.github.com/en/actions/reference/security/secure-use),
[checkout](https://github.com/actions/checkout/releases/tag/v7.0.1),
[setup-python](https://github.com/actions/setup-python/releases/tag/v7.1.0),
[setup-node](https://github.com/actions/setup-node/releases/tag/v7.1.0),
[actionlint](https://github.com/rhysd/actionlint/releases/tag/v1.7.12),
[parseur Babel](https://babeljs.io/docs/babel-eslint-parser/).
