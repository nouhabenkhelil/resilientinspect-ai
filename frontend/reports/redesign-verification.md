# ResilientInspect AI 2.0 — vérification de la refonte

19 novembre 2026. Déploiement local : **http://localhost:18080**.

## Résultat livré

Six espaces React fonctionnels, sans modification du backend, des modules
scientifiques, des poids, des calibrations, des seuils ni des résultats officiels.
Le backend existant est resté démarré pendant la mission. Seul le conteneur
frontend a été reconstruit/remplacé. Les deux conteneurs sont healthy et les
quinze modèles restent disponibles sur CPU.

### Design

Direction « Industrial Intelligence Studio » : surfaces bleu nuit, contours
fins, accent cyan, typographie lisible, iris optique original en SVG, bento
grid et navigation rétractable. Le mode clair est persistant. Les polices
utilisent des fallbacks locaux et ne nécessitent aucun CDN. Le mode
démonstration agrandit la présentation sans simuler de résultat.

Références effectivement consultées :

- [GetDesign](https://getdesign.md/) et [principe DESIGN.md](https://getdesign.md/what-is-design-md).
- [Collection publique VoltAgent](https://github.com/VoltAgent/awesome-design-md).
- [Analyse Linear](https://getdesign.md/linear.app/design-md) : retenue visuelle et hiérarchie de navigation.
- [Analyse Vercel](https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/vercel/DESIGN.md) : lisibilité et organisation des informations techniques.

La palette, le logo et la composition restent propres à ResilientInspect.
Le contrat complet est [DESIGN.md](../DESIGN.md), appliqué aux composants.

### React Bits et dépendances

Quatre composants **réellement importés dans le dashboard** : SpotlightCard,
CountUp, AnimatedList et ShinyText, variantes TypeScript + CSS. Sources du
dépôt officiel figées au commit `d37099f7463b85fd156ab9917d5a58dfa947490f`.
Licence **MIT + Commons Clause**, conservée intégralement ; il ne s’agit pas
d’une licence MIT seule. Les adaptations réduisent les effets sur mobile et
avec prefers-reduced-motion. CountUp anime les compteurs mesurés, jamais les
scores scientifiques. Provenance et modifications dans
[THIRD_PARTY.md](../THIRD_PARTY.md).

Dépendances ajoutées : `lucide-react` 1.76.0, `motion` 14.14.0,
`recharts` 3.11.0 ; `@playwright/test` 1.65.1 en développement.
Le lockfile conserve les versions exactes résolues. React 19.3.1,
TypeScript 7.0.2 et Vite 8.3.8 restent inchangés.

## Fonctionnalités vérifiées

| Espace | Comportement réel |
| --- | --- |
| Control Center | Disponibilité API et modèles, trois catégories, cinq variantes, compteurs des analyses conservées de la session courante, activité récente et macro AUROC officielles |
| Smart Inspection | Sélecteurs et cartes de catégories/modèles disponibles, validation PNG/JPEG, drag/drop, aperçu local, annulation, prédiction puis explication réelles, reprise de la seule visualisation après erreur |
| Explainable viewer | PNG originaux letterbox, image/carte/superposition/côte à côte, zoom, dialogue immersif, téléchargement original et fondu exploratoire explicitement étiqueté |
| Comparison Lab | B0/T2 par défaut, au moins deux modèles, même fichier et catégorie, une requête /predict/visualize à la fois, annulation, résultats partiels et erreurs, accord/désaccord, vérité terrain facultative et TP/TN/FP/FN uniquement si renseignée |
| Model Analytics | Quinze résultats test officiels, filtres catégorie/architecture/métrique, graphiques Recharts et tableaux exacts, macro, confusions, métriques pixel AE seulement, comparaison val synthétique/test réel, coûts paramétriques et provenance |
| System Monitor | Santé, disponibilité par catégorie, raisons d’indisponibilité, versions/SHA, environnement retourné et mesures HTTP de la session ; polling 30 s |
| Historique | 200 métadonnées maximum, recherche et filtres, détails, copie, export CSV/JSON filtré, confirmation avant suppression ; aucune image/base64 persistée |
| Webcam | Activation volontaire, permission navigateur, capture PNG, arrêt après capture/fermeture/démontage ; tests automatisés avec permissions simulées |

Les jauges comparent chaque score à son propre seuil sur une échelle locale
nommée. Les valeurs exactes API sont consultables. Aucun score AE/sigmoid
n’est fusionné ni présenté comme une confiance calibrée. Grad-CAM reste une
attribution relative, distincte d’une segmentation. Aucune reconstruction
d’image absente de l’API n’est inventée.

Le fondu d’exploration combine uniquement l’image préparée et la
superposition API dans les mêmes coordonnées 256×256. Sa position maximale
reproduit l’overlay original ; les PNG téléchargés restent inchangés.

## Données scientifiques

`frontend/scripts/export-analytics.py` produit
`src/data/experiments.json` à partir des archives locales, sans les modifier.
L’export comporte quinze agrégats et 27 références relatives avec SHA256,
protocoles et provenance. Il exclut images, checkpoints, scores individuels,
chemins personnels et secrets. Les métriques de validation synthétique
sont dérivées des scores archivés, au seuil original ; aucun ajustement.

Les dates d’évaluation absentes restent nulles. Les dates de modification
sont identifiées comme provenance des fichiers. Le nombre de paramètres
entraînables A1 absent des sources retenues affiche « Non disponible ».
Aucune courbe ROC/PR ni intervalle artificiel n’est créé.

Conditions rappelées à l’écran : trois catégories, seed 42, apprentissage
Transfer Learning avec anomalies synthétiques, test déjà consulté et absence
de validation indépendante après sélection.

## Contrôles exécutés

- Build TypeScript/Vite : **réussi**, localement puis dans le build Docker.
- Export scientifique `--check` : **15 agrégats authentiques vérifiés**.
- Tests Python de l’export : **4/4 réussis**.
- Tests frontend : **64/64 réussis, neuf fichiers**, avec deux workers ; les
  tests originaux d’inspection sont conservés et ciblent le composant extrait
  SmartInspection.
- `docker compose config --quiet` : **code 0**.
- `docker compose build frontend` puis `up --no-deps --wait frontend` :
  **code 0**, sans reconstruction ni redémarrage du backend.
- `prepare_compose.py --check` : **273 entrées scientifiques inchangées**.
- [Intégration HTTP](http-verification.json) : les quinze prédictions et
  quinze visualisations renvoient **30 HTTP 200**, sans échec, avec de vraies images de validation
  normales autorisées, vérifiées par SHA256 ; aucun PNG artificiel de
  démonstration ne sert de preuve.
- [Vérification Playwright](browser-verification.json) sur le Docker final :
  **passed=true**, zéro erreur JavaScript, 24 contrôles de mise en page
  (4 pages × 3 tailles × 2 thèmes), puis vraie inspection B0 et comparaison
  B0/T2, quatre réponses HTTP 200 et trois entrées d’historique sans image.

Playwright vérifie les débordements globaux et la présence/dimension réelle
des trois graphiques. Les tables larges et le graphique à neuf groupes
défilent à l’intérieur de leur panneau. Les tests de webcam et d’erreurs
réseau simulées sont limités aux tests automatisés, pas à l’application.

Deux défauts détectés puis corrigés pendant la revue : largeur du champ
de fichier masqué provoquant un débordement ; règle max-width sur les
wrappers Recharts réduisant leurs SVG à zéro. La suite navigateur finale
inclut des assertions empêchant de déclarer ces rendus vides réussis.

Un passage Vitest lancé en même temps que Chromium et les inférences CPU
a dépassé le délai de 5 s d’un test de comparaison. La suite finale est
relancée avec deux workers, sans modifier ses assertions ni ses délais.

## Captures locales

Répertoire `frontend/reports/screenshots/`, exclu de Git :

- `desktop-{dark,light}-{dashboard,inspection,comparison,analytics}.png` : 1440×900.
- `laptop-{dark,light}-{dashboard,inspection,comparison,analytics}.png` : 1280×720.
- `mobile-{dark,light}-{dashboard,inspection,comparison,analytics}.png` : 390×844.
- `desktop-real-b0.png` et `desktop-real-comparison-b0-t2.png` : parcours réels.

Les captures sont full-page : leur hauteur totale peut dépasser la hauteur
du viewport. Les pages dashboard, analytics mobile clair et comparaison
réelle ont été inspectées visuellement. Certaines captures contiennent
une image MVTec autorisée localement : elles ne doivent pas être publiées.

## Fichiers créés ou modifiés

- Design/documentation : `DESIGN.md`, `THIRD_PARTY.md`, `README.md`, ce rapport.
- Identité et style : `public/logo.svg`, `index.html`, `src/tokens.css`, `src/styles.css`.
- Shell/navigation : `src/App.tsx`, `src/studio/useSystem.ts`.
- Fonctionnalités : `SmartInspection.tsx`, `ComparisonLab.tsx`, `InspectionTools.tsx`,
  `Webcam.tsx`, `Result.tsx`, `StudioPages.tsx`, `src/studio/history.ts`.
- Mesures : `Analytics.tsx`, `src/data/experiments.json`, `scripts/export-analytics.py`.
- React Bits : composants, CSS, helper reduced motion et licence sous
  `src/components/reactbits/`.
- Tests : suite d’inspection conservée, `Studio.test.tsx`, tests Analytics,
  ComparisonLab, Viewer, Webcam et React Bits, tests Python de l’export,
  `scripts/browser-qa.mjs` et rapports JSON.
- Déploiement frontend : `.dockerignore` autorise le JSON agrégé et le SVG
  original ; `package.json` et `package-lock.json` incluent les dépendances.
- Protection locale : `reports/.gitignore` exclut les captures et artefacts navigateur.

Les Dockerfiles, Nginx, Compose, les modules backend et scientifiques et
les preuves de portabilité ne sont pas modifiés par cette mission.

## Limites restantes

- Webcam matérielle non validée sur un périphérique réel ; ses permissions,
  capture et libération sont testées avec des mocks automatisés.
- Galerie MVTec non distribuée : aucun endpoint de galerie autorisée n’existe
  dans le contrat conservé. Import local et webcam restent disponibles.
- Le bouton d’annulation stoppe l’attente et les requêtes suivantes ; FastAPI
  peut terminer une inférence déjà reçue. Aucun endpoint backend ajouté.
- Historique local plafonné à 200 entrées ; les compteurs de session portent
  sur les entrées conservées depuis le chargement actuel de l’application.
- Les mesures HTTP portent sur un environnement CPU local, pas sur un
  benchmark de production. Aucun audit exhaustif WCAG ou multi-navigateurs
  n’est revendiqué ; la revue navigateur utilise Chromium.
- Aucun ONNX, DVC, MLflow Registry, entraînement ou nouveau réglage scientifique.

## Commandes PowerShell

Depuis la racine :

```powershell
docker compose config --quiet
docker compose build frontend
docker compose up -d --no-deps --wait --wait-timeout 60 frontend
Invoke-RestMethod http://localhost:18080/api/health
npm.cmd --prefix frontend test -- --maxWorkers=2
npm.cmd --prefix frontend run build
& .\.venv\Scripts\python.exe frontend/scripts/export-analytics.py --check
& .\.venv\Scripts\python.exe -m pytest frontend/scripts/tests/test_export_analytics.py -q
& .\.venv\Scripts\python.exe scripts/check_containers.py --output frontend/reports/http-verification.json
npm.cmd --prefix frontend run test:browser
# Arrêter tout le projet lorsque souhaité :
docker compose down
```

Le serveur temporaire de revue sur 5174 est arrêté ; le serveur préexistant
sur 5173 n’a pas été interrompu. Les deux services Docker restent démarrés.
