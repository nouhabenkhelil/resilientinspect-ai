# ResilientInspect AI — Industrial Intelligence Studio

## Vision et identité
Un atelier de vision industrielle précis et calme : le logiciel aide à inspecter,
comparer puis justifier une décision. L’image et les nombres ont priorité sur
la décoration. La signature combine un cadre optique carré, un iris hexagonal
et un centre cyan. Aucun logo ou habillage de marque tierce n’est repris.

Références consultées : https://getdesign.md/ et sa documentation
https://getdesign.md/what-is-design-md ; collection publique
https://github.com/VoltAgent/awesome-design-md ; analyse Vercel (hiérarchie,
espacements, précision des contours), Linear (navigation et densité raisonnée).
Ces analyses sont des inspirations, pas des spécifications copiées.

## Tokens et palette
Les variables de `src/tokens.css` constituent la source du style.
Fond #0B111B ; navigation #0D1420 ; surfaces #111827 et #151F2D ; contour
#253449 ; accent cyan #22D3EE ; accent secondaire #2DD4BF ; texte #F1F5F9 ;
texte secondaire #94A3B8 ; normal #4ADE80 ; anomalie #FB7185 ; attention #FBBF24.
En mode clair : fond #F3F6FA, surface blanche, texte #142033, accent #08758A,
normal #166534, anomalie #BE123C. Une décision possède toujours un libellé.
La couleur ne véhicule jamais seule le sens. Les cartes scientifiques n’ont
aucun effet lumineux derrière une heatmap.

## Typographie et hiérarchie
Contenu : Inter puis Segoe UI/system-ui ; titres : Space Grotesk puis Inter ;
nombres : JetBrains Mono puis Consolas/ui-monospace. Aucun CDN requis : les
fallbacks locaux font partie du rendu prévu. Corps 16px, labels 14px,
métadonnées secondaires 12–13px. Titres 28–38px, graisse 600–700 ; pas de
majuscules massives. Valeurs scientifiques exactes accessibles, chiffres tabulaires.

## Grille et espace
Navigation 248px, rétractée 80px. Contenu max 1600px. Rythme 4/8/12/16/24/32px.
Cartes rayon 14px, boutons 9px, bordure 1px. Bento à 12 colonnes sur grand écran,
deux colonnes sous 1100px puis une colonne sous 720px. La navigation mobile
reste utilisable sans masquer les actions. Aucun débordement global horizontal ;
les tables disposent d’un conteneur de défilement explicite.

## Composants et variantes
Bouton primaire cyan pour lancer une analyse ; secondaire pour configurer ;
texte pour navigation et copie ; danger pour vider l’historique avec confirmation.
Cartes : indicateur, modèle sélectionnable, panneau scientifique, état vide.
Le panneau résultat sépare décision, score/seuil, mesure de temps et provenance.
Les options indisponibles sont désactivées avec une raison lisible.
React Bits locaux : SpotlightCard (halo au pointeur), CountUp (mesures),
AnimatedList (historique réel), ShinyText (signature ponctuelle). Provenance,
licence et adaptations dans THIRD_PARTY.md. Pas de dépendance à un registre
de composants ou service externe à l’exécution.

## États et mouvement
Survol : bordure plus claire ; sélection : contour cyan ; focus : anneau 2px,
offset 3px. Disabled : contraste conservé, curseur explicite. Skeleton limité
au chargement effectif. Pipeline : seulement les événements observables
(validation locale, image prête, requête, résultat reçu, explication).
Scan seulement pendant une vraie requête. Transitions 140–220ms, pas de boucle
permanente. `prefers-reduced-motion` supprime déplacements et animations ;
les halos et effets coûteux sont simplifiés sur écran tactile/mobile.

## Accessibilité et responsive
HTML sémantique, un h1 par page, liens de navigation identifiés, labels de
champs explicites, boutons avec noms accessibles, aria-live pour les erreurs
et états asynchrones, cibles d’au moins 40–44px. Le mode démonstration agrandit
le contenu et replie la navigation sans simuler de données. Pas de focus piégé
hors d’une boîte native ; Escape ferme le visualiseur plein écran.

## Graphiques et rigueur scientifique
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
