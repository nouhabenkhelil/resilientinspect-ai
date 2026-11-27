# Restauration et finition du frontend V3

> Complément motion désormais déployé sur le même service 18180 :
> [MOTION-VERIFICATION.md](MOTION-VERIFICATION.md). Les effets sont prouvés par
> une vidéo locale de 21 secondes et 11 contrôles navigateur du 27 novembre ; seul `web` a
> été remplacé. La composition restaurée ci-dessous reste la référence.

25 novembre 2026 — branche `feature/industrial-platform`, référence `2455699`.

## État final

**La V3 corrigée est réellement servie sur http://localhost:18180.**
`web` est sain ; les 15 autres conteneurs conservent leurs identifiants et
heures de démarrage. Aucune seconde interface n’a été lancée.

À la reprise, les composants restaurés, la palette cyan, les captures A, le
build industriel et le résultat de la relance Vitest à un worker étaient déjà
disponibles. Ils n’ont pas été refaits. La finalisation a vérifié l’image,
remplacé uniquement `web`, exécuté les contrôles navigateur sur le service
déployé et complété les preuves et le rapport.

## Référence et diagnostic

Le dernier commit frontend avant le redesign non committé est `2455699`
(`Implement industrial observability backup and resilience`). Il contient
déjà les fonctionnalités V3 des trois premiers sprints. Les changements de
`App.tsx`, du dashboard, de Batch, des tokens et de la couche de styles ont été
comparés à cette référence sans reset/restore global.

Le service réel est `web`, projet `resilientinspect-industrial`, configuré par
`deployment/industrial/compose.yml` et `deployment/industrial/local/.env`.
Il publie `127.0.0.1:18180` vers Nginx 8080 et utilise le réseau existant
`resilientinspect-industrial_edge`. Il ne monte pas le code frontend en bind :
les assets sont copiés dans l’image à la construction. C’est pourquoi les
modifications locales et l’ancien aperçu Playwright n’étaient pas visibles
dans un navigateur ordinaire sur 18180.

Le mode démonstration appelait aussi `setCollapsed(true)`. Cette action
automatique a été retirée : la sidebar démarre étendue et seul son bouton
explicite change son état. Le choix manuel reste respecté en mode démonstration.

## Correction réalisée

- Ordre initial des dix pages et libellés visibles ; sidebar desktop 264px,
  rétractable à 80px uniquement sur demande. Compte et rôle conservés.
- Header lisible, nom de compte visible lorsque la place le permet.
- Composition initiale du dashboard et schéma du pipeline rétablis ; retrait
  des instruments et encadrements supplémentaires du redesign rejeté.
- Batch retrouve son ordre import → aperçus → paramètres → historique → suivi.
  Le panneau latéral de paramètres a été retiré ; les filtres, explications,
  annulations, exports CSV et listes de fichiers restent disponibles.
- Palette bleu nuit, cyan électrique et turquoise ; boutons principaux plus
  visibles, KPI avec survol discret, badges texte/icône et tables lisibles.
- Libellés de formulaire à 14px, tableaux à 13px et en-têtes à 12px ; pas de
  réduction générale de la typographie pour faire tenir les pages.
- Drawer mobile avec libellés, focus borné, Escape, arrière-plan inerte et
  restitution du focus ; transitions 160–220ms, mouvement réduit respecté.
- Visualisations scientifiques bornées, proportions et couleurs d’origine
  conservées, côte à côte et plein écran maintenus.

Le contrôle des permissions reste celui du serveur. Les raccourcis du
dashboard respectent les permissions existantes. Aucun changement d’OIDC,
de session, d’API, d’inférence, de seuil ou de calibration.

## Vérification et preuves

Le script `scripts/redesign-qa.mjs` utilise maintenant exclusivement le
frontend réellement servi par Docker sur 18180 : aucune interception d’assets,
aucun serveur de prévisualisation ou frontend parallèle. Les tests fonctionnels
utilisent les API réelles sans interception.
L’ancien mode `--preview` a été retiré.

Captures A : ancienne V3 réellement servie avant le remplacement de `web`.
Captures B : V3 corrigée réellement servie après remplacement. Résolutions
identiques 430/1280/1440 × 900px, mêmes thèmes, mêmes comptes. Pendant
l’interruption de session, les journaux sont passés de 36 à 48 inspections
terminées et de 18 à 19 lots. Le contrôle initial a correctement refusé de
présenter ces ensembles différents comme identiques.

Pour les **seules captures comparatives B**, les 36 inspections et les 18 lots
antérieurs ont été retrouvés dans les API réelles par leur date. Leurs données
normalisées correspondent exactement aux SHA256 enregistrés avant :
`c0d1c34688fe2b3128f8ecbb8bd0ce5ee770f0a657ce5ae8cd0a0888217ae7b5`
pour les inspections et
`72039882c6af74d91fe5e0e02675456fd2f4572eff1123a11c9cd28da178dd21`
pour les lots. Ces deux GET sont rejoués uniquement pendant les captures B,
avec les véritables assets du nouveau conteneur. Les routes de relecture sont
ensuite retirées et l’application rechargée avant tout test fonctionnel.
Aucune valeur inventée, modification de base ou injection de frontend.

## Résultats réellement obtenus

| Vérification | Résultat |
| --- | --- |
| TypeScript et ESLint | Réussis, y compris ESLint sur le script de QA final |
| `npm test -- --maxWorkers=1` | **90 tests réussis, 16 fichiers**, 101,82 s |
| `npm run check:contracts` | Six formes de réponses et deux contrats multipart compatibles |
| `npm run check:data` | 15 agrégats scientifiques et 6 agrégats de benchmarks cohérents, non modifiés |
| Build Vite industriel | Réussi, `VITE_PORTAL_MODE=true`, API `/api` |
| Build Docker `web` | Réussi ; images de base, dépendances et Dockerfile inchangés |
| Contenu de l’image avant remplacement | Six fichiers compilés identiques au build local par SHA256 ; archive lue sans conteneur supplémentaire |
| Navigateur sur le service déployé | **33 groupes de contrôles réussis, 159 captures, aucune erreur JavaScript** |
| Responsive | Dix pages × six largeurs × deux thèmes ; aucun débordement global ; libellés desktop visibles |
| Résultats réels responsive | Inspection, comparaison et Batch × six largeurs × deux thèmes ; proportions scientifiques conservées |
| `git diff --check -- frontend` | Réussi |

Le passage concurrent expiré n’est pas compté comme réussi. La relance à un
worker a réussi sans augmenter ni désactiver les délais des tests. Une
collecte initiale des copies de sauvegarde a aussi été corrigée en renommant
ces copies `.snapshot` : le total retenu concerne les 16 vrais fichiers de tests.

Fonctionnalités réellement testées après remplacement :

- Connexions OIDC des quatre rôles ; navigation autorisée, URL directe
  interdite et HTTP 403 serveur pour les non-admins ; session anonyme 401.
- Déconnexion réelle via Keycloak, y compris sa confirmation.
- Les dix pages : Control Center, Inspection, Comparison Lab, Analytics,
  Batch, historique, Monitor/Operations, profil, administration et audit.
- B0/bottle PyTorch : décision normale, score `0.16482834838239885` ;
  ONNX : décision normale, score `0.16482830760864223`. Seuil inchangé
  `0.20367741357625985` ; valeurs exactes affichées égales aux réponses API.
- Comparaison séquentielle B0/T2, reconstruction B0 et Grad-CAM T2 ;
  visualiseur côte à côte, plein écran natif et Escape.
- Lot PostgreSQL existant ouvert : progression et résultats persistants lus.
- Nouveau lot de deux PNG par drag-and-drop, worker jusqu’à 2/2, filtres
  Normal/Anormal/Erreur, contenu CSV vérifié et explication d’image réelle.
- Sidebar étendue et libellés visibles à 1280/1440/1920 ; repli manuel et
  mode démonstration sans repli imposé. Drawer à 390px : Tab/Shift+Tab,
  Escape, retour du focus et restauration du défilement.
- Thèmes clair/sombre et persistance ; préférence de mouvement réduit
  vérifiée par les styles calculés.

Comparaison visuelle : la navigation reprend son ordre et ses noms complets.
Le dashboard conserve la composition de la référence, avec cyan plus présent,
actions plus visibles, KPI mieux délimités, textes secondaires plus lisibles
et marges régulières. Batch retrouve la préparation verticale et sa ligne de
paramètres adaptative. Les captures desktop ne montrent pas de barre uniquement
iconographique. Une capture mobile complémentaire couvre 390 × 844px.

## Remplacement et préservation vérifiés

Un seul remplacement : `resilientinspect-industrial-web-1`, ancien ID
`28731c92ecbd`, nouvel ID `5a685a5be7e1`. Image appliquée :
`sha256:7cfdcf9e35003a5c1fc45b84e93e9510f2048641c004e25519578c0dd89d2422`.
L’image déjà construite a été réutilisée à la reprise. Le HTML servi correspond
au build vérifié et charge `/assets/index-PXVRJzfA.js`.

Port `127.0.0.1:18180`, réseau `resilientinspect-industrial_edge`, racine en
lecture seule et tmpfs existant conservés. Aucun volume de données ajouté.
Les autres conteneurs gardent leurs IDs et heures de démarrage : portal,
worker, science, PostgreSQL, Keycloak, observer, Grafana, Prometheus, services
Hadoop et les deux services Toxiscan. Total : 16 conteneurs en fonctionnement,
15 préservés, `web` sain, aucun OOMKilled relevé. V2 n’a pas été redéployé.

Le relevé de 461 fichiers suivis ou non ignorés ne détecte aucun changement
extérieur à `frontend/`, ni disparition de fichier. Les travaux Sprint 4 sont
conservés. Ce relevé ne compare pas bit à bit les volumes actifs et ne constitue
pas un nouvel inventaire des gros artefacts ignorés.

Preuves locales : `before.json`, `after.json`, `image-verification.json`,
`deployment-verification.json`, `preservation.json`, dans le dossier des captures.

Captures finales principales, avec les assets du nouveau `web` :

- Dashboard : `B-1440-dark-dashboard.png` (comparatif à données historiques
  contrôlées), `after-1440-dark-dashboard.png` (données courantes).
- Inspection : `after-result-single-1440-dark.png`.
- Batch : `after-result-batch-1440-dark.png`.
- Comparaison : `after-result-comparison-1440-dark.png`.
- Mobile : `after-mobile-390.png`.
- Clair : `after-1440-light-dashboard.png`.

Preuves locales ignorées par Git : `reports/screenshots/restore/`.
Les captures et détails peuvent contenir les données privées du portail ; ils
ne sont pas destinés à une publication. Les sources du redesign précédent
ont aussi été conservées dans ce dossier avec l’extension `.snapshot`, pour
éviter leur collecte accidentelle comme tests exécutables.

## Reproduire avec PowerShell

Vérifications frontend, puis build industriel local :

```powershell
Set-Location C:\Users\nouhe\resilientinspect-ai\frontend
npm run typecheck
npm run lint
npm test -- --maxWorkers=1
npm run check:contracts
npm run check:data
$env:VITE_PORTAL_MODE = 'true'
$env:VITE_API_BASE_URL = '/api'
npm run build
```

Construire et remplacer **uniquement le web existant**. La commande `up`
interrompt brièvement l’interface. `--no-deps` évite de recréer ses dépendances :

```powershell
Set-Location C:\Users\nouhe\resilientinspect-ai
$env:COMPOSE_PARALLEL_LIMIT = '1'
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml -p resilientinspect-industrial build web
if ($LASTEXITCODE -ne 0) { throw 'Build web échoué' }
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml -p resilientinspect-industrial up -d --no-build --no-deps --force-recreate web
if ($LASTEXITCODE -ne 0) { throw 'Remplacement web échoué' }
```

Contrôles navigateur sur le service réellement déployé :

```powershell
Set-Location C:\Users\nouhe\resilientinspect-ai\frontend
node .\scripts\redesign-qa.mjs
```

Cette commande crée des inspections et un petit lot par les API normales.
`--access-only` limite la vérification à la navigation, aux rôles et au clavier,
sans créer de nouvelle inférence ni lot. Pour refaire une comparaison A/B,
utiliser `--before` avant remplacement puis `--compare` après. Si les données
ont évolué, le script retrouve les enregistrements antérieurs et exige leur
SHA256 exact avant leur relecture pour les captures B. Si cette preuve n’est
plus disponible, la comparaison échoue volontairement.

## Périmètre et état Git

Fichiers ajustés pendant cette correction : `src/App.tsx`,
`src/components/StudioPages.tsx`, `src/portal/BatchInspection.tsx`,
`src/tokens.css`, `src/premium.css`, `src/Navigation.test.tsx`,
`scripts/redesign-qa.mjs`, `DESIGN.md`, `REDESIGN-VERIFICATION.md` et ce rapport.

Les autres modifications frontend de la demande précédente restent présentes
(badges Admin/History, Operations, couleurs Analytics et import CSS). Les
travaux Sprint 4, configurations et modifications préexistantes extérieures
au frontend sont préservés. Aucun commit, push, reset ou stash.

État Git final : branche `feature/industrial-platform`, HEAD inchangé
`2455699f131178a84dd04793ca06bd450e122d39`. Le cumul des deux demandes frontend
contient 10 fichiers suivis modifiés et 6 fichiers non suivis. Cette restauration
a ajusté les 9 fichiers listés ci-dessus et créé ce rapport ; les différences
préexistantes hors frontend restent identiques au relevé initial.

Aucun changement du Compose, des images de base, des dépendances, des réseaux
ou des volumes. Aucun lancement staging, nouvel environnement Docker,
entraînement, benchmark scientifique ou déploiement public.

## Limites

Validation locale Chromium ; pas de certification WCAG exhaustive ni test de
charge. Les parcours réels ciblent B0/bottle PyTorch/ONNX et B0/T2 pour la
comparaison ; ils ne refont pas l’évaluation scientifique des 15 modèles et
14 graphes. L’annulation et les erreurs restent couvertes par les tests
unitaires existants. Aucune révocation de session d’un autre utilisateur ni
modification de compte.

Les tests réels ajoutent leurs enregistrements d’inspection, de lot et d’audit
par les API autorisées. Aucun enregistrement antérieur ni volume n’est effacé.
La sécurité Sprint 4 reste non finalisée : cette correction frontend ne valide
ni le staging HTTPS ni une ouverture Internet.
