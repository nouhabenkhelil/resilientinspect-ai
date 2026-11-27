# ResilientInspect AI — Industrial Intelligence Studio

## Vision et identité
Un atelier de vision industrielle précis et calme : le logiciel aide à inspecter,
comparer puis justifier une décision. L’image et les nombres ont priorité sur
la décoration. La signature combine un cadre optique carré, un iris hexagonal
et un centre cyan. L’interface utilise un cyan électrique pour ses actions et un
turquoise discret pour son identité. Aucun habillage de marque tierce n’est repris.

Références consultées : https://getdesign.md/ et sa documentation
https://getdesign.md/what-is-design-md ; collection publique
https://github.com/VoltAgent/awesome-design-md ; analyse Vercel (hiérarchie,
espacements, précision des contours), Linear (navigation et densité raisonnée).
Ces analyses sont des inspirations, pas des spécifications copiées.

## Tokens et palette
Les variables de `src/tokens.css` constituent la source du style.
Fond bleu nuit #0B1220 ; navigation #0E1828 ; surfaces #121E30 et #19283B ; contour
#2C4058 ; accent cyan #29D8ED ; secondaire #2DD4BF ; texte #F1F7FF ;
texte secondaire #A7B8CE ; normal #6CE3A1 ; anomalie #FF8AA1 ; attention #F6C66C.
En mode clair : fond #F3F5F8, surface blanche, texte #18253A, accent #08758A,
normal #17633F, anomalie #B52B46. Une décision possède toujours un libellé.
La couleur ne véhicule jamais seule le sens. Les cartes scientifiques n’ont
aucun effet lumineux derrière une heatmap.

## Typographie et hiérarchie
Contenu : Inter puis Segoe UI/system-ui ; titres : Space Grotesk puis Inter ;
nombres : JetBrains Mono puis Consolas/ui-monospace. Aucun CDN requis : les
fallbacks locaux font partie du rendu prévu. Corps de contenu 13–16px,
labels de formulaire 14px, tables 13px, en-têtes 12px. Titres 28–36px ; pas de
majuscules massives. Valeurs scientifiques exactes accessibles, chiffres tabulaires.

## Grille et espace
Navigation 264px, étendue par défaut, rétractée à 80px uniquement sur demande.
Ordre des pages repris de la V3 du commit 2455699, sans groupes intercalés.
Contenu max 1720px. Rythme 4/8/12/16/20/24/32/40px.
Cartes rayon 14px (12px sur mobile), contrôles 9px, bordure 1px. Grilles
adaptatives ; KPI sur deux colonnes sur tablette/mobile. Drawer sous 1000px,
grille principale simplifiée sous 650px, marges mobiles 16px. Aucun débordement global horizontal ;
les tables disposent d’un conteneur de défilement explicite.

## Composants et variantes
Bouton primaire cyan pour lancer une analyse ; secondaire pour configurer ;
texte pour navigation et copie ; danger pour vider l’historique avec confirmation.
Cartes : indicateur, modèle sélectionnable, panneau scientifique, état vide.
Le panneau résultat sépare décision, score/seuil, mesure de temps et provenance.
Les options indisponibles sont désactivées avec une raison lisible.
`StatusBadge` associe texte et icône aux états ; les états inconnus restent
neutres. Les services exposent leur disponibilité réelle, sans compteur simulé.
Batch retrouve son enchaînement original : import, aperçus, paramètres sur
une ligne adaptative, puis historique et suivi réel. Le dashboard conserve
son hero à deux colonnes et son schéma initial ; les cadres et marges ajoutés
par le redesign précédent ont été retirés.
La liste complète des fichiers se déplie sans créer de nouveaux Object URLs.
React Bits locaux : SpotlightCard (halo au pointeur), CountUp (mesures),
AnimatedList (historique réel), ShinyText (signature ponctuelle). Provenance,
licence et adaptations dans THIRD_PARTY.md. Pas de dépendance à un registre
de composants ou service externe à l’exécution.

## États et mouvement
Survol : bordure plus claire et déplacement de 1–2px ; sélection : contour cyan ; focus : anneau 2px,
offset 3px. Disabled : contraste conservé, curseur explicite. Skeleton limité
au chargement effectif. Pipeline : seulement les événements observables
(validation locale, image prête, requête, résultat reçu, explication).
Scan seulement pendant une vraie requête. Transitions 160–220ms, pas de boucle
permanente. `prefers-reduced-motion` supprime déplacements et animations ;
les halos et effets coûteux sont simplifiés sur écran tactile/mobile.

## Accessibilité et responsive
HTML sémantique, un h1 par page, liens de navigation identifiés, labels de
champs explicites, boutons avec noms accessibles, aria-live pour les erreurs
et états asynchrones, cibles d’au moins 40–44px. Le mode démonstration agrandit
le contenu sans simuler de données ni replier automatiquement la navigation. Le drawer mobile
place le focus dans la navigation, borne Tab/Shift+Tab, rend le contenu en
arrière-plan inerte et restaure focus/défilement à la fermeture. Escape ferme
le drawer et le visualiseur plein écran. Les liens et raccourcis d’inspection
respectent les permissions existantes ; les contrôles serveur restent la référence.

## Graphiques et rigueur scientifique

Le mouvement complémentaire est défini dans `src/motion.css`, sans changement
de composition ni de palette : titre 360ms, hero 420ms, KPI 440ms avec départs
110/200/290/380ms, CountUp 750ms une fois, hover 180–200ms, navigation/drawer
260ms, résultat à l’entrée du viewport 380ms, vue scientifique en fondu 240ms.
La transition d’image ne transforme pas l’image ni son zoom. Les graphiques
interpolent leurs mesures existantes sur 380ms. La progression Batch interpole
uniquement entre deux valeurs retournées par le serveur, sur 380ms ; le texte
et le progress natif accessible gardent immédiatement les nombres exacts.
Le balayage et les spinners n’existent que pendant une requête réelle.
En reduced-motion, mouvements, délais et CountUp sont supprimés.
Recharts pour les agrégats officiels : axes nommés, légende, unité et source.
Tables textuelles pour les valeurs exactes et lecteur d’écran. Les valeurs
absentes affichent « Non disponible ». Aucun zéro substitué à une absence.
Confusions : TP/TN/FP/FN et catégorie/split visibles. AE et sigmoid possèdent
des scores différents : pas d’axe commun de scores bruts, ni fusion arbitraire.
La jauge compare un score à son propre seuil avec une échelle locale étiquetée.
ROC/PR uniquement si les points réels sont exportés ; aucune courbe dessinée
à partir de la seule AUROC. Statistiques de session et mesures du dataset
sont séparées. Cartes API conservées en letterbox 256×256 avec couleurs et
échelles originales ; opacité d’exploration explicitement signalée.

## Interdits
Pas de données de démonstration fictives, uptime inventé, jauge CPU/RAM sans
endpoint, confiance probabiliste inventée, reconstru­ction non retournée,
Grad-CAM appelée segmentation, images MVTec publiées, chemins personnels,
secrets, gradients omniprésents, verre flou, clignotement ou ambiance jeu vidéo.
