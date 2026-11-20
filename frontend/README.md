# ResilientInspect AI 2.0 — Industrial Intelligence Studio

L’extension ONNX ajoute un sélecteur de moteur explicite dans Smart Inspection,
une comparaison technique de moteurs dans Comparison Lab, les moteurs réels
dans l’historique et une section Performance Engineering dans Model Analytics.
La disponibilité ONNX provient exclusivement de l’API et de ses preuves.
Les mesures d’inférence restent distinctes des résultats de classification.
Une explication Grad-CAM d’une prédiction ONNX est clairement identifiée
comme produite par PyTorch, avec contrôle de cohérence.

Après démarrage du déploiement ONNX validé :

```powershell
node frontend/scripts/onnx-qa.mjs
& .\.venv\Scripts\python.exe scripts/check_onnx_api.py
```

La refonte ajoute six espaces : Control Center, Smart Inspection, Comparison
Lab, Model Analytics, System Monitor et Historique. L’application conserve
les quatre endpoints FastAPI et le proxy `/api`, sans changement du backend.

Le [DESIGN.md](DESIGN.md) fixe les tokens, composants, comportements et règles
scientifiques. Les quatre composants React Bits intégrés et leur licence
MIT + Commons Clause sont documentés dans [THIRD_PARTY.md](THIRD_PARTY.md).
Les résultats et limites de vérification figurent dans
[reports/redesign-verification.md](reports/redesign-verification.md).

## Exécution et vérification de la version 2.0

Depuis la racine, avec FastAPI local sur 8000 pour Vite :

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run dev
```

Pour utiliser le backend Docker existant sur 8001 pendant le développement :

```powershell
$env:API_PROXY_TARGET = 'http://127.0.0.1:8001'
npm.cmd --prefix frontend run dev
```

Reconstruction du seul frontend Docker, sans recréer le backend sain :

```powershell
docker compose config --quiet
docker compose build frontend
docker compose up -d --no-deps --wait --wait-timeout 60 frontend
docker compose ps
Invoke-RestMethod http://localhost:18080/api/health
```

Ouvrir <http://localhost:18080>. Oracle conserve le port 8080.

```powershell
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
& .\.venv\Scripts\python.exe frontend/scripts/export-analytics.py --check
& .\.venv\Scripts\python.exe -m pytest frontend/scripts/tests/test_export_analytics.py -q
& .\.venv\Scripts\python.exe scripts/check_containers.py --output frontend/reports/http-verification.json
Push-Location frontend
npm.cmd exec playwright install chromium
npm.cmd run test:browser
Pop-Location
```

Le test navigateur utilise une image de validation normale locale, vérifiée
par SHA256, et l’API réelle. Les captures restent dans
`frontend/reports/screenshots/`, exclues de Git car certaines contiennent
des images autorisées du dataset. Aucun dataset n’est ajouté au bundle.
`UI_TEST_URL` permet de choisir une autre URL pour Playwright.

Les métriques publiques sont un export agrégé et versionné de quinze rapports,
avec 27 références de sources et empreintes. Pour le régénérer explicitement :

```powershell
& .\.venv\Scripts\python.exe frontend/scripts/export-analytics.py
```

La comparaison exécute une seule requête `/predict/visualize` à la fois, sans
fusionner les scores ni modifier les seuils. L’annulation coupe l’attente et
les requêtes suivantes ; un calcul déjà reçu par FastAPI peut terminer.
Les latences de cette page incluent l’explication. Les compteurs du dashboard
reposent sur les entrées conservées pendant le chargement courant de
l’application, avec une limite de 200 entrées locales. Le rechargement ouvre
une nouvelle session de compteurs. Aucun PNG ni image brute n’est conservé.

La webcam exige un clic volontaire et l’autorisation du navigateur ; elle
s’arrête après capture, fermeture ou changement de page. Aucune galerie MVTec
n’est distribuée. Le mode démonstration ne fait qu’agrandir l’interface.

## Parcours d’inspection conservé

Interface locale d’inspection pour la validation du **24 novembre 2026**.
React, TypeScript et Vite ; styles CSS locaux, sans police distante ni jeu de données embarqué.
Les quatre endpoints FastAPI existants sont utilisés. Aucun changement backend,
modèle, checkpoint ou calibration n’est nécessaire et aucun n’a été effectué.

## Démarrage Windows

Prérequis : Node.js **22.12 ou ultérieur** et l’environnement scientifique Python
du projet déjà opérationnel. Versions npm figées dans `package-lock.json`.

Dans un premier terminal, depuis la racine du dépôt :

```powershell
& .\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
& .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Attendre `Application startup complete`. Si cette API fonctionne déjà sur le
port 8000, la réutiliser. Le chargement initial vérifie les quinze couples
modèle/catégorie. Voir aussi `../backend/README.md` pour les prérequis scientifiques.

Dans un second terminal :

```powershell
cd frontend
npm install
npm run dev
```

Ouvrir <http://127.0.0.1:5173>. Dans PowerShell, si `npm.ps1` est bloqué par la
politique d’exécution, utiliser **`npm.cmd install`**, **`npm.cmd run dev`**, etc.
Il n’est pas nécessaire de modifier cette politique. Le port Vite est fixe ;
un port déjà occupé déclenche une erreur explicite.

1. Choisir une catégorie puis un modèle disponible dans les métadonnées.
2. Importer ou déposer une image PNG/JPEG fixe, 10 Mio et 20 Mpx au maximum.
3. Cliquer sur **Analyser l’image**. L’aperçu avant ce clic reste local.
4. Lire la décision, le score, le seuil, le modèle, la catégorie, les latences,
   le SHA de version et l’identifiant de `/predict`.
5. Explorer la superposition, la carte seule ou l’image préparée. Les détails
   fournissent les coordonnées, le padding et l’identifiant distinct de la visualisation.

## Configuration de l’API

La configuration par défaut fonctionne sans fichier `.env` :

```dotenv
VITE_API_BASE_URL=/api
API_PROXY_TARGET=http://127.0.0.1:8000
```

Pour la modifier, copier `.env.example` vers `.env.local` dans `frontend/`,
puis redémarrer Vite. `VITE_API_BASE_URL` est l’URL publique lue par le service
centralisé `src/api/client.ts`. Elle est intégrée au bundle à la compilation et
ne doit jamais contenir de secret. Elle peut être relative ou absolue.

Le proxy Vite **dev et preview** retire `/api` avant de transmettre la requête
à `API_PROXY_TARGET`. Cela permet d’utiliser le backend inchangé, qui n’expose
pas de configuration CORS. Pour une future publication des fichiers `dist/`,
un serveur devra assurer ce routage sur la même origine, ou le backend devra
être configuré pour une origine externe autorisée. Le proxy Vite n’est pas
embarqué dans les fichiers statiques. Cette mission s’arrête à la revue locale.

Références : [variables Vite](https://vite.dev/guide/env-and-mode),
[proxy Vite](https://vite.dev/config/server-options#server-proxy).

## Contrats respectés

Contrats analysés avant implémentation : `backend/app/main.py`,
`backend/app/schemas.py`, `backend/app/models.py`, puis limites d’entrée et rendu
dans `config.py`, `imaging.py` et `inference.py`.

| Requête                   | Contrat et comportement frontend                                                                                                                                                     |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `GET /health`             | Lit `status`, `version`, `device`, `ready_models`, `expected_models`, `request_id`. Le HTTP 503 avec `status: degraded` reste un état exploitable.                                   |
| `GET /model/metadata`     | Lit `models`, `unavailable`, `request_id`. Le sélecteur est alimenté par les modèles réellement disponibles pour la catégorie ; les indisponibilités sont désactivées et expliquées. |
| `POST /predict`           | Multipart avec exactement `file`, `category`, `model`. Affiche `decision`, `anomaly_score`, `threshold`, `model`, `category`, `inference_time_ms`, `version`, `request_id`.          |
| `POST /predict/visualize` | Second multipart identique. Utilise les trois PNG base64 de `visualization`, son `kind`, ses dimensions, son échelle et son padding.                                                 |

Catégories : `bottle`, `hazelnut`, `leather`. Modèles : `B0`, `A1`, `T0`, `T1`, `T2`.
Les contrats TypeScript reprennent les noms et types des schémas FastAPI.
Les erreurs `code`, `message`, `request_id` sont préservées dans `ApiError` ;
le message et l’identifiant sont affichés. Les réponses HTML de proxy et les
échecs réseau produisent aussi des messages lisibles.

Les GET sont vérifiés au démarrage, toutes les 30 secondes, et à la demande.
Un état dégradé autorise les couples disponibles. Un serveur injoignable ou
l’absence de métadonnées empêche une nouvelle analyse. Délais : 10 secondes
pour les GET, 120 secondes par POST. Les contrôles de configuration et
d’import sont verrouillés pendant l’analyse. Changer le fichier, la catégorie
ou le modèle efface les résultats précédents. Les URL d’aperçu sont révoquées.

La prédiction reste visible si la visualisation échoue. **Réessayer la
visualisation** ne renvoie que ce second POST. **Annuler l’attente** interrompt
les requêtes côté navigateur ; cela ne garantit pas l’arrêt du calcul CPU
déjà engagé côté FastAPI.

## Interprétation des résultats

- La décision provient de FastAPI : `anomaly` est affiché **Anormal** et `normal`
  **Normal**. La règle serveur est strictement `score > threshold`.
- Les nombres de score et de seuil sont affichés avec six décimales ; cet
  arrondi d’affichage ne recalcule pas la décision serveur.
- B0/A1 : erreur de reconstruction RGB, **pas une probabilité**. La heatmap
  représente l’erreur L1 absolue [0, 1], padding exclu.
- T0/T1/T2 : sigmoid du logit anomalie, sans prétendre à une probabilité
  calibrée. Grad-CAM est une attribution grossière relative à chaque image,
  **pas une segmentation pixel** ni un contour de défaut.
- Les images serveur restent en coordonnées `letterbox_256`, 256 × 256,
  avec padding noir. Aucune remise à l’échelle vers des coordonnées de défaut
  dans l’image originale n’est revendiquée.
- La latence API est `inference_time_ms`. L’aller-retour `/predict` mesuré par
  le navigateur est affiché séparément. Le second POST refait une inférence
  pour produire l’explication et porte son propre identifiant et sa latence.

## Tests et build

```powershell
npm test
npm run build
npm run preview
```

Le build exécute TypeScript en mode strict puis Vite. `preview` sert le
résultat sur <http://127.0.0.1:4173> avec le même proxy local.

Les tests Vitest / Testing Library utilisent des réponses contrôlées **dans
les tests seulement**. Ils vérifient les contrats multipart, les erreurs HTTP,
la santé dégradée, les délais et annulations, les fichiers invalides, l’import,
les changements de paramètres, l’affichage, les explications et les reprises.
L’application n’a aucun mode démonstration simulé ni réponse de secours fictive.

Avec FastAPI et Vite dev démarrés, lancer également :

```powershell
npm run test:integration
```

Ce script exerce réellement les quatre endpoints via le proxy, tous les
couples disponibles et les deux POST pour chacun. Il génère en mémoire une
image RGB uniforme 173 × 89, vérifie les seuils des métadonnées, décisions,
scores identiques entre les deux POST, identifiants HTTP et PNG 256 × 256.
Il vérifie aussi le rejet HTTP 415 d’un fichier GIF. Aucun fichier MVTec
n’est chargé ni distribué. Le rapport est `reports/api-verification.json`.

Pour utiliser le serveur preview à la place :

```powershell
$env:API_TEST_URL = 'http://127.0.0.1:4173/api'
npm run test:integration
Remove-Item Env:API_TEST_URL
```

## Vérification du 17 novembre 2026 et limites

- 36 tests frontend réussis (3 fichiers).
- 46 tests backend existants réussis :
  `.\.venv\Scripts\python.exe -m pytest tests/test_backend_api.py -q -W error --tb=short`.
- Intégration réelle en développement puis sur le build servi par `preview` :
  15 couples disponibles et 30 POST HTTP 200 par exécution, avec rejet du
  fichier invalide en HTTP 415. Page de production servie en HTTP 200.
  Le rapport fourni conserve la dernière exécution sur `preview`, sans image embarquée.
- Build TypeScript + Vite réussi ; sources et lockfile disponibles pour revue.
- Le contrôle visuel dans le navigateur n’a pas pu être effectué : l’accès au
  navigateur intégré était indisponible et l’outil Computer Use a interrompu
  l’accès à Chrome faute de pouvoir déterminer son URL avec assez de certitude.
  La revue visuelle desktop/mobile reste donc à faire. Le responsive est prévu
  en CSS aux seuils 1200, 980, 720 et 380 px, avec respect de la réduction des animations.

La validation locale par image synthétique vérifie l’intégration, pas la
performance de détection sur des produits réels. Les contrôles de contenu,
d’animation et de correspondance extension/format restent autoritaires côté
backend. Pas d’authentification, d’historique persistant, de traitement par lot
ni d’exposition publique ajoutés. Aucune conteneurisation ni intégration ONNX.

## Fichiers livrés

```text
frontend/
  .env.example             Configuration locale documentée
  .gitignore               Exclusion des dépendances et sorties
  .prettierrc.json          Formatage des sources
  .prettierignore           Exclusion des fichiers générés du formatage
  README.md                Lancement, contrats, vérifications et limites
  package.json             Dépendances et commandes npm
  package-lock.json        Versions reproductibles
  index.html               Point d’entrée français
  tsconfig.json            Contrôle TypeScript strict
  vite.config.ts           React et proxy dev/preview
  vitest.config.ts         Environnement des tests
  public/favicon.svg       Icône vectorielle locale
  scripts/check-api.mjs     Vérification contre le vrai backend
  reports/api-verification.json   Preuves des échanges réels
  src/
    main.tsx               Montage React
    App.tsx                Page Inspection et orchestration
    styles.css             Interface responsive
    image.ts               Validation locale des fichiers et dimensions
    image.test.ts          Tests des limites d’image
    App.test.tsx           Tests des parcours et états
    api/contracts.ts       Types des schémas FastAPI
    api/client.ts          Service HTTP centralisé
    api/client.test.ts     Tests des contrats HTTP
    components/Icon.tsx    Icônes SVG locales
    components/Result.tsx  Décision, métriques et explications
    test/fixtures.ts       Données réservées aux tests
    test/setup.ts          Configuration Testing Library
```

`node_modules/` et `dist/` sont générés et ignorés par Git.
**Arrêt pour revue avant conteneurisation.**
