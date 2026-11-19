# Composants tiers du studio

## React Bits — composants intégrés, TypeScript + CSS

Sources gratuites officielles : [React Bits](https://reactbits.dev/),
[installation](https://reactbits.dev/get-started/index),
[dépôt DavidHDev/react-bits](https://github.com/DavidHDev/react-bits).

Les quatre composants de `src/components/reactbits/` sont issus du commit
**`d37099f7463b85fd156ab9917d5a58dfa947490f`**, version légère antérieure à
React Bits 2.0. Ce choix conserve des composants lisibles et sans effets
WebGL/GSAP, avec une seule dépendance d'animation commune : `motion/react`.
Le code est embarqué dans l'application ; aucun CDN ni accès réseau n'est
nécessaire à son exécution. Les sources et la licence ont été consultées.

| Composant | Variante et source figée | Dépendances | Adaptations locales |
| --- | --- | --- | --- |
| Spotlight Card | [TS-CSS SpotlightCard](https://github.com/DavidHDev/react-bits/blob/d37099f7463b85fd156ab9917d5a58dfa947490f/src/ts-default/Components/SpotlightCard/SpotlightCard.tsx) | React, CSS | Couleurs/rayons via tokens ; halo cyan local ; suppression des événements et du halo sur mobile, pointeur tactile et reduced motion. |
| Count Up | [TS-CSS CountUp](https://github.com/DavidHDev/react-bits/blob/d37099f7463b85fd156ab9917d5a58dfa947490f/src/ts-default/TextAnimations/CountUp/CountUp.tsx) | React, motion/react | Valeur finale statique en reduced motion/mobile ; libellé accessible exact ; garde durée nulle et fallback navigateur sans IntersectionObserver. Réservé aux compteurs mesurés, jamais aux scores scientifiques. |
| Animated List | [TS-CSS AnimatedList](https://github.com/DavidHDev/react-bits/blob/d37099f7463b85fd156ab9917d5a58dfa947490f/src/ts-default/Components/AnimatedList/AnimatedList.tsx) | React, motion/react, CSS | Liste sémantique, boutons natifs lorsqu'une action existe, tabulation libre ; suppression de l'interception globale du clavier et des éléments de démonstration ; animation d'entrée unique et limitée ; styles responsives. |
| Shiny Text | [TS-CSS ShinyText](https://github.com/DavidHDev/react-bits/blob/d37099f7463b85fd156ab9917d5a58dfa947490f/src/ts-default/TextAnimations/ShinyText/ShinyText.tsx) | React, CSS | Élément inline ; reflet unique sur l'identité, pas d'animation permanente ; rendu statique reduced motion/mobile. |

Les quatre composants utilisent `useReducedEffects.ts` pour réagir aux
préférences d'accessibilité et au changement de taille/pointeur. Les effets
ne modifient aucun résultat et ne sont pas employés sur les heatmaps.

### Licence conservée

La licence de cette révision est **MIT + Commons Clause License Condition
v1.0**, Copyright (c) 2025 David Haz. Ce n'est pas une licence MIT seule.
Elle autorise notamment l'usage et la modification dans une application,
un site ou un produit, tout en interdisant la vente, sous-licence ou
redistribution des composants eux-mêmes en tant que tels. L'intégration
présente est une utilisation dans ResilientInspect AI, pas un catalogue
de composants à redistribuer.

Le texte original complet est conservé sans modification dans
[`src/components/reactbits/LICENSE.md`](src/components/reactbits/LICENSE.md).

## Dépendances npm

Les versions installées sont figées par `package-lock.json`. Motion sert
aux animations des compteurs et listes ; Recharts aux graphiques de métriques
authentiques. Les dépendances et leurs licences restent dans leurs packages.
Aucune dépendance runtime à un service payant ou à un CDN n'est introduite.
