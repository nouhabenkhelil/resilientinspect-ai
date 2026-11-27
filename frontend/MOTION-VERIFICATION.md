# Motion V3 — vérification du 27 novembre 2026

La V3 est déployée sur **http://localhost:18180**, dans le Compose industriel existant. Le design restauré, la palette, la structure et les libellés de la sidebar desktop étendue sont conservés. Aucune dépendance ajoutée.

## Corrections de cette passe

Les animations précédentes démarraient au montage, même lorsque les cartes étaient sous la ligne de flottaison. Les KPI, le résumé graphique, les résultats Smart Inspection et les cartes Comparison Lab attendent maintenant leur première visibilité (12 % du panneau), puis ne rejouent plus à chaque polling. `RevealSection` réutilise `useInView` de la dépendance Motion déjà présente ; aucun nouvel outil d’animation.

Le départ du CountUp est synchronisé avec la cascade des KPI. Son texte est initialisé avant le premier affichage avec `useLayoutEffect`, supprimant le bref flash valeur finale → zéro observé pendant la vérification. Les mises à jour suivantes restent immédiates et exactes. Les valeurs accessibles restent les véritables cibles API.

Le balayage couvre la hauteur réelle de l’aperçu avec un transform en pourcentage. Il existe uniquement pendant les requêtes d’inférence/explication, sans attente minimale. Le texte précise qu’il s’agit d’un effet d’attente. Les barres graphiques et la jauge ont une entrée par transform, leurs valeurs et seuils restant inchangés. La navigation revient immédiatement en haut du nouveau contenu pour rendre son entrée visible.

## Animations effectivement présentes

| Élément | Déclenchement / durée |
| --- | --- |
| Titre et hero | Navigation : 360 / 420 ms |
| KPI | Première visibilité : 440 ms ; cascade à 110, 200, 290, 380 ms |
| CountUp React Bits | 750 ms ; mêmes départs que les KPI ; aucune remise à zéro au polling |
| SpotlightCard React Bits | Halo cyan au pointeur 180 ms ; élévation 4 px et bordure 200 ms |
| Graphiques du résumé et jauge | Première visibilité : 420 ms, délai 100 ms ; largeurs scientifiques conservées |
| Upload / drag-over | Bordure, halo et déplacement 180 ms ; focus clavier également visible |
| Prévisualisation image | 320 ms, y compris dans Comparison Lab |
| Scan / indicateur de traitement | 1 100 ms par passage, uniquement pendant la vraie requête |
| Résultats et cartes comparatives | Première visibilité : 380 ms |
| Décision / score / seuil | 380 / 360 ms ; scores en cascade à 100 et 180 ms |
| Image / heatmap / overlay | Fondu 240 ms ; zoom conservé |
| Sélection des modèles | 260 ms ; bordure 180 ms ; focus visible |
| Désaccord réel | Entrée 320 ms et deux accents de 650 ms, uniquement si les décisions diffèrent |
| Fichiers Batch | 320 ms ; cascade plafonnée à 220 ms |
| Barre Batch | Interpolation 380 ms entre les seules valeurs reçues du backend ; progress accessible exact |
| États et lignes Batch | 220 / 260 ms ; pas de réanimation sur polling identique |
| CSV / annulation | Spinner pendant la promesse réelle ; retour après réponse |
| Navigation / drawer mobile | Contenu 260 ms, liens 180 ms, drawer 260 ms |
| Thème sombre / clair | Couleurs et surfaces 240 ms |

AnimatedList et ShinyText React Bits restent utilisés. Pas d’animation décorative infinie ajoutée. Les effets de pointeur sont désactivés sur tactile. `prefers-reduced-motion` supprime mouvements et délais, affiche directement les compteurs exacts et masque le balayage.

## Validation exécutée

- TypeScript strict : réussi.
- ESLint, zéro avertissement : réussi.
- Vitest complet : **92 tests réussis dans 16 fichiers** (124,18 s, un worker).
- Après les derniers ajustements : **16 tests navigation/comparaison** et **5 tests React Bits** relancés avec succès.
- Contrats des six réponses et des multipart : réussis.
- Build Vite local et build Vite/TypeScript de l’image industrielle finale : réussis.
- **11 contrôles navigateur réussis**, zéro erreur de page, sur le vrai service 18180.

Le script ne remplace ni les API ni leurs réponses et ne retarde aucune requête :

1. KPI en cascade et CountUp vers les **15 modèles réellement disponibles**, valeurs intermédiaires puis valeur exacte ; 28 échantillons de compteur enregistrés.
2. Actualisation API sans relancer le CountUp.
3. Halo suivant le pointeur et élévation mesurés dans les styles calculés.
4. Résumé initialement hors écran : animation en pause puis entrée à la visibilité, une seule fois.
5. Transition réelle du thème clair/sombre et entrée du titre à la navigation.
6. Inférence **T2/bottle réelle** : 62 échantillons du scan pendant la requête, arrêt après réponse ; 5 échantillons intermédiaires du fondu résultat ; seuil exact, transition heatmap et zoom 150 % conservé.
7. Comparaison séquentielle **B0/T2 réelle** : sélection animée, deux cartes révélées et scores/seuils identiques aux réponses API.
8. Lot réel de trois PNG : réponses backend **0/3 queued → 3/3 completed**, 49 échantillons de barre avec interpolation visible ; CSV téléchargé et feedback de fin. Aucun pourcentage inventé.
9. Mobile **390 × 900** : drawer animé, libellés visibles, Escape, restitution du focus, aucun débordement global.
10. Mouvement réduit **1440 × 900** : compteurs immédiatement exacts, scan masqué pendant une vraie inférence, résultat immédiatement visible.
11. Desktop compact **1280 × 900** : sidebar étendue, capture après la fin des entrées, aucun débordement global.

Le test initial du nouveau contrôle Comparison Lab a été interrompu par un sélecteur ambigu partagé avec Engine Duel. Il a été précisé sur la liste d’architectures ; les deux passages suivants ont réussi. Les essais interrompus ne sont pas comptés comme validations.

Les modèles sont concordants sur l’image de comparaison testée. L’accent de désaccord reste conditionné aux vraies décisions ; aucun désaccord artificiel injecté. L’annulation et les états d’erreur sont couverts par les tests de composants existants, sans provoquer d’incident backend dans cette passe navigateur.

## Preuves locales

- [Vidéo en mouvement — 20,92 s, 1440 × 900, 25 images/s, 6,26 Mo](reports/screenshots/motion/2026-11-27/motion-proof.webm).
- [Mesures navigateur et réponses réelles](reports/screenshots/motion/2026-11-27/verification.json).
- [Identités et démarrages des conteneurs](reports/screenshots/motion/2026-11-27/containers.json).
- Captures desktop, inspection, comparaison, Batch, mobile, compact et mouvement réduit dans ce même dossier.

La vidéo commence après la connexion OIDC. Identifiants, cookies et état de session ne sont pas enregistrés. Elle contient les images et résultats locaux du portail et reste dans le dossier de preuves ignoré par Git. Une image a été extraite avec FFmpeg pour vérifier le décodage ; les captures statiques ne sont pas présentées comme preuve de mouvement.

## Déploiement

Seul `resilientinspect-industrial-web-1` a été reconstruit et remplacé avec `--no-build --no-deps --force-recreate web`. Il est sain. Les **15 autres conteneurs** ont conservé leurs identifiants et dates de démarrage. Aucun second frontend ou staging lancé.

Image finale : `sha256:b22f1a21efb67a42a91fa9b4db64934d3670a5b28690ad28d15a9b2ce8994b4e`.
Asset principal : `/assets/index-5-j2DPzj.js`.

Le rendu a été contrôlé dans l’onglet Chrome existant après Ctrl+F5, avec sidebar et navigation visibles. Les contrôles enregistrés chargent également les assets réels de 18180 depuis de nouveaux contextes navigateur.

Backend scientifique, modèles, seuils, API, worker, Keycloak, PostgreSQL, DVC/MLflow et travaux Sprint 4 : aucun changement dans cette mission. Les tests réels créent uniquement leurs inspections et lots habituels via les API autorisées. Aucun commit ni push.

## Fichiers modifiés dans cette passe

- `src/App.tsx` : retour en haut à la navigation et identifiant de révision motion.
- `src/motion.css` : attente de visibilité, entrée des barres/jauge, balayage adaptatif et feedback clavier.
- `src/components/RevealSection.tsx` : révélation unique au viewport, préférence de mouvement respectée.
- `src/components/StudioPages.tsx` : KPI et résumé au viewport, départs CountUp synchronisés.
- `src/components/Result.tsx` : panneau et animations enfants au viewport.
- `src/components/ComparisonLab.tsx` : cartes au viewport et aperçu animé.
- `src/components/reactbits/SpotlightCard.tsx` : révélation optionnelle sans changer le halo existant.
- `src/components/reactbits/CountUp.tsx` : initialisation du texte avant affichage.
- `scripts/motion-qa.mjs` : preuves datées, comparaison réelle, panneau hors écran, responsive et inférence en mode réduit.
- `MOTION-VERIFICATION.md`, `RESTORE-VERIFICATION.md` : rapport et lien vers les preuves à jour.

Les autres modifications déjà présentes dans le dépôt ont été conservées.

## Reproduire

```powershell
Set-Location C:\Users\nouhe\resilientinspect-ai\frontend
npm run typecheck
npm run lint
npm test -- --maxWorkers=1
$env:VITE_PORTAL_MODE = 'true'
$env:VITE_API_BASE_URL = '/api'
npm run build
Set-Location ..
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml -p resilientinspect-industrial build web
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml -p resilientinspect-industrial up -d --no-build --no-deps --force-recreate web
Set-Location frontend
node scripts/motion-qa.mjs
```
