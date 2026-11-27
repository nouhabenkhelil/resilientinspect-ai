# ResilientInspect AI V3 — Role Theme Verification

27 novembre 2026 — version réellement déployée sur **http://localhost:18180**.

## Résultat

Finition de la V3 existante, sans changement de layout, de navigation, de permissions ou de backend. Admin et AI Engineer ont des identités nettement distinctes en clair et en sombre. Operator et Auditor conservent la palette neutre. Le Hero dispose d’une illustration SVG originale, également visible sur mobile.

Les **93 tests Vitest** et les **22 contrôles navigateur** passent. Les quatre comptes de test sont réellement authentifiés via l’OIDC existant. Aucune substitution d’API, d’assets ou de rôle dans les captures.

## Identité et session

`App.tsx` applique `data-role` au shell à partir de `usePortalAuth().user.role`, uniquement en mode portail et lorsque l’authentification est disponible. Le provider existant masque l’application pendant la vérification de session et après expiration/déconnexion. Aucun thème privé n’est appliqué à la page anonyme. Le rôle n’est pas lu depuis localStorage, les URL ou les préférences de thème.

- **Admin :** fond graphite/violet `#151122`, surfaces `#211A30`, accent violet `#B49AFF`, indigo et détails magenta ; tracés géométriques diagonaux et halo discret.
- **AI Engineer :** fond bleu nuit `#081422`, surfaces `#101F32`, cyan `#22D3EE`, turquoise et bleu ; trame de circuits très fine.
- **Operator / Auditor :** mêmes tokens neutres que la V3 restaurée ; leurs autorisations restent inchangées.
- Les variantes claires utilisent des surfaces blanches, des fonds très légèrement teintés et des accents plus foncés pour conserver le contraste.
- Le rôle est écrit explicitement dans le badge de compte et dans la sidebar ; il ne dépend pas de la couleur seule.
- La préférence `ri.theme` reste indépendante du rôle. Le test réel Admin → déconnexion → AI Engineer dans le même contexte conserve le mode clair, retire le thème privé durant l’état anonyme et reçoit bien un 401 avant reconnexion.

Les tokens `--normal`, `--anomaly`, `--warning` et les couleurs des séries scientifiques ne sont pas redéfinis par les rôles. Les états gardent leurs couleurs sémantiques vert, rouge/rose et ambre. Les motifs et halos restent derrière les surfaces ; aucun effet ajouté sur les PNG scientifiques.

## Hero et palette

L’asset [industrial-ai-hero.svg](src/assets/industrial-ai-hero.svg) est une composition native originale de **7 115 octets** : portique avec caméra, convoyeur en perspective, bouteille stylisée, ligne de scan, nœuds de réseau et région d’interprétation conceptuelle. Il ne contient ni photo MVTec, ni image externe, ni logo tiers, ni script, ni filtre, ni métrique ou décision simulée.

Le SVG est intégré depuis un asset local de confiance pour hériter des variables CSS. Son contenu est décoratif (`aria-hidden`) et ne reçoit aucune donnée d’inférence. La légende visible précise : « Illustration conceptuelle · aucune analyse en cours ».

Les boutons primaires reçoivent un dégradé très léger vers l’accent secondaire ; les KPI, bordures actives, sélections, onglets, imports et progression reprennent l’accent du rôle. Le halo SpotlightCard hérite désormais de la palette, au lieu de forcer un cyan identique pour tous. Les tables restent sobres et les images explicatives inchangées.

## Animations et responsive

Les composants CountUp, SpotlightCard, RevealSection, scan d’inférence, fondu des résultats, progression Batch et navigation sont réutilisés.

| Ajout | Durée et comportement |
| --- | --- |
| Entrée de l’illustration | 450 ms, délai 120 ms |
| Pulsation de nœuds | 1 800 ms × 3 ; arrêt après 5,4 s |
| Ligne de scan décorative | 2 400 ms × 2 ; arrêt après 4,8 s |
| Hover de l’illustration | Translation de 3 px, 220 ms, pointeur fin uniquement |
| Couleurs et surfaces du shell | 260 ms ; transitions existantes des cartes 200–240 ms |
| Halo de fond | Statique ; aucune animation plein écran ni timer |

Les mouvements utilisent transform et opacity. Avec `prefers-reduced-motion`, les trois animations du Hero sont désactivées et l’illustration statique reste complète. Les effets de pointeur existants restent supprimés sur tactile.

**390, 768, 1280, 1440 et 1920 px**, en clair et sombre, ont été contrôlés pour Admin et AI Engineer : **20 combinaisons** sans débordement global, SVG visible et ratio 600/420 conservé. À 390 px, le Hero passe en colonne, les boutons précèdent l’illustration et restent utilisables. Sidebar étendue sur desktop ; drawer mobile avec focus borné, Escape et restitution du focus conservés.

## Validation exécutée

| Vérification | Résultat |
| --- | --- |
| TypeScript strict | Réussi |
| ESLint, zéro avertissement | Réussi |
| Vitest complet | **93 / 93**, 16 fichiers, 81,57 s, un worker |
| Contrats API | Six formes de réponse et multipart inchangés |
| Build Vite local | Réussi |
| Build Docker industriel `web` | Réussi |
| Rôles, sessions et captures | **11 contrôles réussis**, 13 captures, zéro erreur de page |
| Régression motion et parcours réels | **11 contrôles réussis**, zéro erreur de page |

Contrôles réels de rôle : Admin, AI Engineer, Operator, Auditor ; navigation autorisée, raccourcis autorisés, accès direct Administration refusé pour les trois rôles non administrateurs, véritable GET `/api/admin/users` = 403, session anonyme = 401, aucune identité privée anonyme. Operations Center et les détails de l’historique persistant sont ouverts pour Admin et AI Engineer ; les listes viennent du BFF/PostgreSQL existant.

Parcours scientifiques réels : inférence T2/bottle, attente avec 97 échantillons de scan, décision et seuil exacts, transition heatmap et zoom 150 % conservé ; comparaison B0/T2 séquentielle ; lot de trois images avec réponses **0/3 queued → 3/3 completed**, 47 échantillons de barre et export CSV. Les 28 échantillons de CountUp montrent les valeurs intermédiaires puis la cible exacte, sans redémarrage au rafraîchissement. Le mouvement réduit est également testé pendant une vraie inférence.

### Préservation scientifique

Une comparaison automatique avec la preuve de la V3 précédente confirme l’égalité exacte des scores, seuils et décisions B0/T2 sur la même image, ainsi que du moteur et de la version du modèle T2.

- T2 : score `0.00003256561467424035`, seuil `0.00017796678002923727`, décision `normal`.
- B0 : score `0.16482834838239885`, seuil `0.20367741357625985`, décision `normal`.

[Preuve d’égalité scientifique](reports/role-theme/2026-11-27/scientific-equivalence.json). Les latences peuvent varier et ne sont pas confondues avec ces résultats scientifiques.

## Captures et vidéos

Captures de véritables sessions, même page et même viewport **1440 × 1000**, sans retouche. Les nombres du journal diffèrent légitimement selon le périmètre de chaque rôle ; aucune donnée n’est uniformisée artificiellement.

| Rôle | Sombre | Clair |
| --- | --- | --- |
| Admin | [Dashboard dark](reports/role-theme/2026-11-27/admin-dashboard-dark.png) | [Dashboard light](reports/role-theme/2026-11-27/admin-dashboard-light.png) |
| AI Engineer | [Dashboard dark](reports/role-theme/2026-11-27/ai_engineer-dashboard-dark.png) | [Dashboard light](reports/role-theme/2026-11-27/ai_engineer-dashboard-light.png) |

- [Mobile Admin 390 px](reports/role-theme/2026-11-27/admin-mobile-390-light.png), [Mobile AI Engineer 390 px](reports/role-theme/2026-11-27/ai_engineer-mobile-390-dark.png).
- [Hero industriel en grand format](reports/role-theme/2026-11-27/industrial-hero-large.png).
- [Reconnexion Engineer après Admin](reports/role-theme/2026-11-27/same-session-engineer-after-admin-logout.png).
- [Hero statique en mouvement réduit](reports/role-theme/2026-11-27/reduced-motion-static-hero.png).
- [Vidéo Hero, hover, thème et navigation — 9,16 s, 1440 × 1000, 25 i/s](reports/role-theme/2026-11-27/role-theme-proof.webm).
- [Vidéo des parcours et animations d’inférence/Batch](reports/role-theme/2026-11-27/motion/motion-proof.webm).
- [Mesures rôles/responsive](reports/role-theme/2026-11-27/verification.json), [mesures motion/API](reports/role-theme/2026-11-27/motion/verification.json).

L’enregistrement commence après l’authentification. Identifiants, cookies et état de session ne sont pas sauvegardés. Les preuves locales restent dans `frontend/reports/`, ignoré par Git. Une image extraite avec FFmpeg confirme le décodage de la vidéo ; les captures statiques seules ne sont pas présentées comme preuve de mouvement.

## Performance et limites

Aucune dépendance ajoutée. Aucun WebGL, canvas 3D, filtre SVG ou animation de fond continue. Les boucles décoratives sont bornées ; aucun timer React ajouté.

La mesure locale sans vidéo, sur le dashboard Engineer pendant les animations du Hero, donne **151 intervalles sur environ 2,5 s : médiane 16,7 ms, p95 16,8 ms**, soit près de 60 images/s sur ce passage. [Mesure](reports/role-theme/2026-11-27/performance.json). Cela ne constitue pas une garantie de fréquence sur tout matériel ou sous charge. La capture vidéo automatisée entraîne davantage de variabilité et n’est pas utilisée comme benchmark du rendu seul.

Le JS principal est de **502,49 Ko / 158,15 Ko gzip**, soit environ **1,67 Ko gzip de plus** que la passe motion précédente. Le CSS est de **70,06 Ko / 14,53 Ko gzip**, environ **1,23 Ko gzip de plus**. Vite émet son avertissement indicatif de chunk supérieur à 500 Ko ; le build réussit et aucune limite n’a été désactivée ou relevée.

Les tests portent sur Chromium/Chrome local ; pas de certification Safari/Firefox. Aucun désaccord scientifique ou incident serveur artificiel injecté. La génération du CSV et les états existants sont conservés ; les tests de composants couvrent les branches d’annulation et d’erreur.

## Déploiement et périmètre

Seul `resilientinspect-industrial-web-1` a été reconstruit/remplacé, avec le Compose industriel et le port 18180 existants. Il est **healthy**. Les **15 autres conteneurs** gardent leurs identifiants et dates de démarrage. Volumes conservés ; aucun autre frontend ou environnement démarré.

Image appliquée : `sha256:0c6ee17d47e8f5119abe1d643cfde9e4a3e444ce23c017f255e722992484349c`.
Assets servis : `index-DRXec3Id.js`, `index-BW8HhMxB.css`. Les deux suites navigateur chargent cette version après déploiement, depuis des contextes réels neufs.

L’onglet Chrome existant a également été rechargé avec Ctrl+F5 : thème Engineer, rôle explicite, illustration, sidebar étendue et API opérationnelle observés.

[Audit des conteneurs](reports/role-theme/2026-11-27/containers.json), [audit des sources](reports/role-theme/2026-11-27/source-audit.json). Aucun changement hors frontend par cette mission. Backend, checkpoints, calibrations, seuils, ONNX, API, Keycloak, RBAC, PostgreSQL, migrations, worker, DVC/MLflow et staging/Sprint 4 préservés. Les tests utilisent uniquement les écritures normales d’inspections/lots via les API existantes. Aucun commit ni push.

L’audit constate aussi l’apparition concurrente d’un environnement `.venv-prefect/` hors frontend, sans intervention de cette mission. Il est laissé intact ; aucun fichier préexistant hors frontend n’a changé par rapport au relevé initial.

## Fichiers concernés

- `src/App.tsx` : rôle authentifié sur le shell, libellé explicite du compte.
- `src/role-themes.css` : tokens des rôles en clair/sombre, palette, fonds, Hero et responsive.
- `src/assets/industrial-ai-hero.svg` : illustration vectorielle originale.
- `src/components/IndustrialHero.tsx` : intégration décorative et légende explicite.
- `src/components/StudioPages.tsx` : nouvel asset à la place du schéma ; halo hérité du thème.
- `src/components/reactbits/SpotlightCard.tsx` : couleur CSS héritée quand aucune couleur n’est imposée.
- `src/main.tsx` : import de la couche de finition.
- `src/Navigation.test.tsx` : tests du rôle authentifié, de sa suppression, de la préférence claire et de l’absence d’effet d’un rôle localStorage.
- `scripts/role-theme-qa.mjs` : rôles réels, reconnexion, responsive, captures, vidéo et accessibilité.
- `scripts/motion-qa.mjs` : destination de preuves configurable et libellé de halo indépendant du rôle ; anciennes preuves préservées.
- `reports/role-theme/.gitignore` : preuves locales exclues de Git.
- `ROLE-THEME-VERIFICATION.md` : ce rapport.

## Reproduire les contrôles

```powershell
Set-Location C:\Users\nouhe\resilientinspect-ai\frontend
npm run typecheck
npm run lint
npm test -- --maxWorkers=1
npm run check:contracts
$env:VITE_PORTAL_MODE = 'true'
$env:VITE_API_BASE_URL = '/api'
npm run build
Set-Location ..
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml -p resilientinspect-industrial build web
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml -p resilientinspect-industrial up -d --no-build --no-deps --force-recreate web
Set-Location frontend
node scripts/role-theme-qa.mjs
$env:MOTION_QA_OUTPUT = 'frontend/reports/role-theme/2026-11-27/motion'
node scripts/motion-qa.mjs
```
