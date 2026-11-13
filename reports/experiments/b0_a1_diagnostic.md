# Diagnostic scientifique complémentaire B0/A1

Date : 13 novembre 2026. Audit des archives officielles `f515662ab4ef`, sans entraînement, reconstruction de checkpoint, inférence ou recalibration. Le rapport de premier suivi est conservé.

## Périmètre et statut des analyses

Les résultats du protocole initial restent les six `metrics.json` sous `reports/evaluation/{b0,a1}/f515662ab4ef`. Les AUROC/AP image, F1 image, Dice/IoU micro, AUROC/AP pixel et moyennes par catégorie ci-dessous reprennent ces archives ; les valeurs image et les recouvrements sont aussi recalculés depuis les CSV. Les matrices et distributions visualisent les mêmes décisions. Les courbes n'introduisent aucun seuil opérationnel nouveau.

Les ventilations par défaut, intervalles bootstrap et interprétations diagnostiques sont **post-hoc descriptifs**. Aucun résultat ne sert à sélectionner une variante ou modifier les seuils, hyperparamètres, splits ou protocoles. Les documents de protocole antérieurs décrivaient une étape préparatoire ; leur ancien statut ne remplace pas l'existence des archives finales auditées ici.

## Contrôles d'identité et de provenance

Tous les contrôles ont réussi : 317 images test distinctes, 170 images validation distinctes. B0 et A1 utilisent exactement les mêmes identifiants, catégories, labels, défauts, chemins de masques, pixels valides et cibles positives après resize. Pas de doublon, image manquante ou supplémentaire face au manifeste et à l'arborescence test PNG. Train/val/test sont disjoints par chemin et SHA256 déclaré ; train et val sont normaux et issus de train officiel. Les SHA256 réels des images test/val et masques test correspondent au manifeste.

Protocole SHA256 : `f515662ab4ef0437194f7fdc7b57c8ea435ae6cb7e1be95c26476a91fa5d963e`. Manifeste SHA256 : `13f55c7cf7c87a3e3739e24920bb0d85cc96a39a00e30d277ddfaa1832b84522`. Codes Dataset et évaluation commune présents identiques à leurs empreintes archivées. Les six checkpoints ont été hachés, sans chargement. Les empreintes des calibrations, leurs compagnons SHA256 et leur liaison checkpoint/manifeste/protocole ont été vérifiés.

Prétraitement commun : RGB [0,1], letterbox 256×256, bilinéaire image, nearest masque ; padding exclu. Carte = erreur absolue RGB moyenne, sans lissage. Score = moyenne des `ceil(0,01 × N_valides)` plus grandes erreurs ; décision **strictement > seuil**. Seuils issus de validation normale : quantile image 0,95 et pixel 0,995, méthode `higher`, propres à chaque modèle/catégorie. Les six seuils image sont retrouvés depuis les scores val archivés ; les seuils pixel sont contrôlés pour intégrité et cohérence, mais leur quantile ne peut pas être recalculé sans les erreurs pixel val absentes des CSV. Aucun recalcul de calibration n'a été exécuté.

| Modèle | Catégorie | n test | n val | Seuil image | Seuil pixel | FPR image val |
| --- | --- | --- | --- | --- | --- | --- |
| B0 | bottle | 83 | 42 | 0.203677 | 0.145293 | 0.047619 |
| A1 | bottle | 83 | 42 | 0.143756 | 0.099174 | 0.047619 |
| B0 | hazelnut | 110 | 79 | 0.116357 | 0.078412 | 0.037975 |
| A1 | hazelnut | 110 | 79 | 0.276115 | 0.142381 | 0.037975 |
| B0 | leather | 124 | 49 | 0.083305 | 0.072442 | 0.040816 |
| A1 | leather | 124 | 49 | 0.080454 | 0.058639 | 0.040816 |

Les effectifs, décisions, agrégats TP/FP/FN, Dice/IoU micro, moyennes par image anormale et moyennes macro correspondent aux JSON (tolérance numérique 1e−12). Les scores pixel continus ne sont pas archivés dans les CSV : AUROC/AP pixel sont repris des JSON, sans prétendre les recalculer ni leur fournir des IC. La réalité de chaque carte prédite ne peut pas être revérifiée sans ses valeurs pixel ; l'audit vérifie ses comptages archivés et sa cible.

## Résultats confirmés aux seuils du protocole initial

| Catégorie | Modèle | TP | FP | FN | TN | Rappel | FPR test | F1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bottle | B0 | 32 | 1 | 31 | 19 | 0.507937 | 0.050000 | 0.666667 |
| bottle | A1 | 38 | 0 | 25 | 20 | 0.603175 | 0.000000 | 0.752475 |
| hazelnut | B0 | 41 | 0 | 29 | 40 | 0.585714 | 0.000000 | 0.738739 |
| hazelnut | A1 | 11 | 0 | 59 | 40 | 0.157143 | 0.000000 | 0.271605 |
| leather | B0 | 91 | 32 | 1 | 0 | 0.989130 | 1.000000 | 0.846512 |
| leather | A1 | 68 | 29 | 24 | 3 | 0.739130 | 0.906250 | 0.719577 |

![Matrices de confusion](b0_a1_diagnostic_local/confusion.png)

### Différences A1 − B0

Valeurs absolues, et non pourcentages relatifs. Dice/IoU = segmentation micro sur toutes les images de la catégorie, normales incluses. Macro = moyenne non pondérée des trois catégories ; aucun mélange des scores de modèles/catégories distincts.

| Catégorie | Métrique | B0 | A1 | A1 − B0 |
| --- | --- | --- | --- | --- |
| bottle | AUROC image | 0.711111 | 0.807143 | 0.096032 |
| bottle | AP image | 0.908374 | 0.943050 | 0.034676 |
| bottle | F1 image | 0.666667 | 0.752475 | 0.085809 |
| bottle | Dice micro | 0.078650 | 0.094038 | 0.015388 |
| bottle | IoU micro | 0.040935 | 0.049339 | 0.008404 |
| bottle | AUROC pixel | 0.752425 | 0.770028 | 0.017603 |
| bottle | AP pixel | 0.145525 | 0.187069 | 0.041544 |
| hazelnut | AUROC image | 0.931786 | 0.937500 | 0.005714 |
| hazelnut | AP image | 0.962271 | 0.964775 | 0.002505 |
| hazelnut | F1 image | 0.738739 | 0.271605 | -0.467134 |
| hazelnut | Dice micro | 0.504390 | 0.264751 | -0.239640 |
| hazelnut | IoU micro | 0.337247 | 0.152572 | -0.184675 |
| hazelnut | AUROC pixel | 0.934174 | 0.913679 | -0.020495 |
| hazelnut | AP pixel | 0.505420 | 0.498944 | -0.006476 |
| leather | AUROC image | 0.747962 | 0.624321 | -0.123641 |
| leather | AP image | 0.914228 | 0.872252 | -0.041976 |
| leather | F1 image | 0.846512 | 0.719577 | -0.126935 |
| leather | Dice micro | 0.139598 | 0.074104 | -0.065494 |
| leather | IoU micro | 0.075036 | 0.038478 | -0.036559 |
| leather | AUROC pixel | 0.832973 | 0.747426 | -0.085547 |
| leather | AP pixel | 0.201310 | 0.120047 | -0.081264 |
| macro | AUROC image | 0.796953 | 0.789655 | -0.007298 |
| macro | AP image | 0.928291 | 0.926693 | -0.001598 |
| macro | F1 image | 0.750639 | 0.581219 | -0.169420 |
| macro | Dice micro | 0.240879 | 0.144297 | -0.096582 |
| macro | IoU micro | 0.151073 | 0.080129 | -0.070943 |
| macro | AUROC pixel | 0.839858 | 0.810378 | -0.029480 |
| macro | AP pixel | 0.284085 | 0.268687 | -0.015398 |

### Distributions et courbes image

Les histogrammes normalisent séparément chaque classe (somme des hauteurs = 1), avec les mêmes bins B0/A1 par catégorie. Les scores sont des erreurs brutes, pas des probabilités ; leurs amplitudes ne mesurent pas directement la qualité entre modèles. Les lignes verticales sont les seuils validation archivés.

![Distributions](b0_a1_diagnostic_local/score_distributions.png)

ROC et PR utilisent les scores continus ; les points indiquent les décisions strictes au seuil val. AP est la moyenne de précision non interpolée scikit-learn, pas l'aire trapézoïdale PR. La ligne de prévalence rappelle le déséquilibre des classes. Aucune optimisation de F1 ou de seuil sur test.

![ROC](b0_a1_diagnostic_local/roc.png)

![Precision–Recall](b0_a1_diagnostic_local/pr.png)

## Analyse post-hoc par type de défaut

AUROC/AP/F1 « vs good » comparent chaque défaut aux mêmes images normales de sa catégorie. Les normales sont réutilisées entre sous-groupes : les lignes ne sont pas des réplications indépendantes et ne doivent pas être sommées. TP/FN/rappel portent sur le défaut ; FP/TN portent sur les normales communes. Dice/IoU de cette table agrègent seulement les images du défaut (leurs FP pixel inclus), donc excluent les FP pixel des normales ; ils ne remplacent pas la segmentation primaire toutes images. Une AUROC sur le seul sous-groupe anormal serait indéfinie.

| Catégorie | Modèle | Défaut | n défaut | TP | FN | FP good | TN good | Rappel | AUROC vs good | AP vs good | F1 vs good | Dice défaut | IoU défaut |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bottle | B0 | broken_large | 20 | 10 | 10 | 1 | 19 | 0.500000 | 0.770000 | 0.829609 | 0.645161 | 0.077125 | 0.040109 |
| bottle | B0 | broken_small | 22 | 16 | 6 | 1 | 19 | 0.727273 | 0.831818 | 0.891125 | 0.820513 | 0.205274 | 0.114376 |
| bottle | B0 | contamination | 21 | 6 | 15 | 1 | 19 | 0.285714 | 0.528571 | 0.659730 | 0.428571 | 0.030517 | 0.015495 |
| bottle | A1 | broken_large | 20 | 15 | 5 | 0 | 20 | 0.750000 | 0.955000 | 0.963902 | 0.857143 | 0.086923 | 0.045436 |
| bottle | A1 | broken_small | 22 | 17 | 5 | 0 | 20 | 0.772727 | 0.897727 | 0.937425 | 0.871795 | 0.253281 | 0.145004 |
| bottle | A1 | contamination | 21 | 6 | 15 | 0 | 20 | 0.285714 | 0.571429 | 0.691258 | 0.444444 | 0.036674 | 0.018680 |
| hazelnut | B0 | crack | 18 | 11 | 7 | 0 | 40 | 0.611111 | 0.920833 | 0.884717 | 0.758621 | 0.462535 | 0.300843 |
| hazelnut | B0 | cut | 17 | 3 | 14 | 0 | 40 | 0.176471 | 0.841176 | 0.697569 | 0.300000 | 0.394594 | 0.245791 |
| hazelnut | B0 | hole | 18 | 10 | 8 | 0 | 40 | 0.555556 | 0.963889 | 0.942950 | 0.714286 | 0.533074 | 0.363395 |
| hazelnut | B0 | print | 17 | 17 | 0 | 0 | 40 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | 0.678585 | 0.513529 |
| hazelnut | A1 | crack | 18 | 0 | 18 | 0 | 40 | 0.000000 | 0.915278 | 0.879323 | 0.000000 | 0.129185 | 0.069053 |
| hazelnut | A1 | cut | 17 | 0 | 17 | 0 | 40 | 0.000000 | 0.880882 | 0.740986 | 0.000000 | 0.171482 | 0.093782 |
| hazelnut | A1 | hole | 18 | 0 | 18 | 0 | 40 | 0.000000 | 0.954167 | 0.918683 | 0.000000 | 0.239601 | 0.136106 |
| hazelnut | A1 | print | 17 | 11 | 6 | 0 | 40 | 0.647059 | 1.000000 | 1.000000 | 0.785714 | 0.608392 | 0.437186 |
| leather | B0 | color | 19 | 19 | 0 | 32 | 0 | 1.000000 | 0.718750 | 0.560844 | 0.542857 | 0.056618 | 0.029134 |
| leather | B0 | cut | 19 | 19 | 0 | 32 | 0 | 1.000000 | 0.597039 | 0.655768 | 0.542857 | 0.168651 | 0.092091 |
| leather | B0 | fold | 17 | 17 | 0 | 32 | 0 | 1.000000 | 0.941176 | 0.937127 | 0.515152 | 0.315081 | 0.187000 |
| leather | B0 | glue | 19 | 18 | 1 | 32 | 0 | 0.947368 | 0.582237 | 0.654261 | 0.521739 | 0.206989 | 0.115442 |
| leather | B0 | poke | 18 | 18 | 0 | 32 | 0 | 1.000000 | 0.930556 | 0.915320 | 0.529412 | 0.061432 | 0.031689 |
| leather | A1 | color | 19 | 17 | 2 | 29 | 3 | 0.894737 | 0.625000 | 0.486504 | 0.523077 | 0.009513 | 0.004779 |
| leather | A1 | cut | 19 | 8 | 11 | 29 | 3 | 0.421053 | 0.287829 | 0.393247 | 0.285714 | 0.279057 | 0.162153 |
| leather | A1 | fold | 17 | 16 | 1 | 29 | 3 | 0.941176 | 0.862132 | 0.851051 | 0.516129 | 0.191523 | 0.105903 |
| leather | A1 | glue | 19 | 9 | 10 | 29 | 3 | 0.473684 | 0.424342 | 0.590399 | 0.315789 | 0.137073 | 0.073579 |
| leather | A1 | poke | 18 | 18 | 0 | 29 | 3 | 1.000000 | 0.965278 | 0.937721 | 0.553846 | 0.024266 | 0.012282 |

### Masques après redimensionnement

Contrôle direct avec `letterbox_pair` existant : 225 masques anormaux, 0 devenu(s) vide(s), 0 vide(s) après resize au total. Les pixels positifs redimensionnés sont exactement TP+FN dans B0 et A1. L'inventaire par image, y compris surfaces natives et redimensionnées, est dans `mask_audit.csv`.

## Bootstrap apparié descriptif post-hoc

2000 réplications, seed 42, NumPy `default_rng` (PCG64). Tirage avec remise **des images**, stratifié par catégorie et label normal/anormal : effectifs et prévalence sont conservés. Les mêmes indices sont utilisés pour B0 et A1, pour toutes les métriques. Les seuils et checkpoints restent fixes ; aucune recalibration dans une réplication. Dice/IoU agrègent les TP/FP/FN des images tirées, normales comprises, puis calculent le ratio ; aucun pixel n'est traité comme une observation indépendante. La macro est recalculée dans chaque réplication comme moyenne des trois catégories fixes. IC percentiles 2,5–97,5 %, sans correction de multiplicité. Toutes les réplications ont les deux classes et des dénominateurs non nuls.

Ces IC sont conditionnels aux modèles entraînés, aux catégories et à la prévalence observée ; ils ne couvrent ni variabilité d'entraînement, ni choix du checkpoint, ni incertitude de calibration, ni nouveaux sites/catégories. Ils supposent les images échangeables dans chaque strate et ignorent d'éventuels groupes de production inconnus. Un intervalle excluant zéro reste une indication descriptive post-hoc, sans test confirmatoire ni causalité.

| Catégorie | Métrique | B0 [IC 95 %] | A1 [IC 95 %] | Δ [IC 95 %] |
| --- | --- | --- | --- | --- |
| bottle | AUROC image | 0.711111 [0.599206 ; 0.811131] | 0.807143 [0.709484 ; 0.889683] | 0.096032 [0.035714 ; 0.164286] |
| bottle | AP image | 0.908374 [0.868038 ; 0.943816] | 0.943050 [0.911933 ; 0.968445] | 0.034676 [0.012055 ; 0.058789] |
| bottle | F1 image | 0.666667 [0.551724 ; 0.776699] | 0.752475 [0.645161 ; 0.844037] | 0.085809 [0.014793 ; 0.160841] |
| bottle | Dice micro | 0.078650 [0.059758 ; 0.102712] | 0.094038 [0.071679 ; 0.123213] | 0.015388 [0.009998 ; 0.022142] |
| bottle | IoU micro | 0.040935 [0.030799 ; 0.054136] | 0.049339 [0.037172 ; 0.065651] | 0.008404 [0.005414 ; 0.012375] |
| hazelnut | AUROC image | 0.931786 [0.884634 ; 0.968571] | 0.937500 [0.893902 ; 0.972857] | 0.005714 [-0.011795 ; 0.027143] |
| hazelnut | AP image | 0.962271 [0.937995 ; 0.982415] | 0.964775 [0.939562 ; 0.985038] | 0.002505 [-0.009306 ; 0.014523] |
| hazelnut | F1 image | 0.738739 [0.640777 ; 0.823529] | 0.271605 [0.133333 ; 0.390805] | -0.467134 [-0.593939 ; -0.350763] |
| hazelnut | Dice micro | 0.504390 [0.470551 ; 0.543914] | 0.264751 [0.200996 ; 0.346343] | -0.239640 [-0.284243 ; -0.180613] |
| hazelnut | IoU micro | 0.337247 [0.307661 ; 0.373545] | 0.152572 [0.111726 ; 0.209441] | -0.184675 [-0.211102 ; -0.147272] |
| leather | AUROC image | 0.747962 [0.657609 ; 0.829492] | 0.624321 [0.529543 ; 0.717739] | -0.123641 [-0.183441 ; -0.066236] |
| leather | AP image | 0.914228 [0.880798 ; 0.945007] | 0.872252 [0.831481 ; 0.909618] | -0.041976 [-0.065518 ; -0.019830] |
| leather | F1 image | 0.846512 [0.835681 ; 0.851852] | 0.719577 [0.655556 ; 0.775510] | -0.126935 [-0.190956 ; -0.072790] |
| leather | Dice micro | 0.139598 [0.109646 ; 0.169793] | 0.074104 [0.054309 ; 0.094327] | -0.065494 [-0.079995 ; -0.050395] |
| leather | IoU micro | 0.075036 [0.058003 ; 0.092772] | 0.038478 [0.027912 ; 0.049498] | -0.036559 [-0.045498 ; -0.027643] |
| macro | AUROC image | 0.796953 [0.747670 ; 0.842348] | 0.789655 [0.743342 ; 0.834695] | -0.007298 [-0.037069 ; 0.023271] |
| macro | AP image | 0.928291 [0.908959 ; 0.945890] | 0.926693 [0.908674 ; 0.944037] | -0.001598 [-0.013145 ; 0.009902] |
| macro | F1 image | 0.750639 [0.700613 ; 0.795490] | 0.581219 [0.521173 ; 0.633624] | -0.169420 [-0.222831 ; -0.119107] |
| macro | Dice micro | 0.240879 [0.224049 ; 0.258492] | 0.144297 [0.120097 ; 0.173403] | -0.096582 [-0.111960 ; -0.075838] |
| macro | IoU micro | 0.151073 [0.139236 ; 0.164812] | 0.080129 [0.064807 ; 0.099934] | -0.070943 [-0.080387 ; -0.057637] |

## Conclusions et limites

**Confirmé au protocole initial :** A1 améliore bottle en classement image, F1 et segmentation micro, mais la segmentation y reste faible (Dice 0,0940). Sur hazelnut, l'AUROC image progresse légèrement (0,9318 → 0,9375), tandis que le rappel au seuil val chute de 41/70 à 11/70 et le Dice de 0,5044 à 0,2648. Un bon classement ne garantit donc pas une bonne décision au seuil fixé. Sur leather, B0 classe toutes les 32 normales positives ; A1 en classe 29/32 positives et manque 24/92 anomalies contre 1/92 pour B0, avec dégradation AUROC/AP/F1 et Dice/IoU. Le F1 élevé de B0 leather doit se lire avec ce FPR de 100 % et la prévalence anormale élevée. A1 n'améliore pas uniformément B0 ; aucune supériorité générale n'est établie.

**Interprétation post-hoc :** les distributions et sous-groupes localisent les modes d'échec aux seuils existants ; ils ne prouvent pas leur cause. Les écarts de scores entre normales val et test, notamment leather, sont compatibles avec un décalage de distribution sans en identifier l'origine. La validation a aussi servi à sélectionner les checkpoints, et n'est donc pas une validation indépendante de la calibration. Les IC par images décrivent seulement l'incertitude conditionnelle précisée ci-dessus. Aucun réglage correctif ni choix T0/T1/T2 n'est effectué à partir du test.

## Reproduction, fichiers locaux et conservation

Commande depuis la racine :

```powershell
& .venv/Scripts/python.exe scripts/diagnose_b0_a1.py
```

Le script ne charge aucun modèle et ne contient aucun appel d'inférence ou d'entraînement. Il s'arrête si une incohérence de données, provenance, seuil, métrique ou conservation est détectée. Les figures et tables exactes se trouvent dans le dossier **ignoré par Git** `reports/experiments/b0_a1_diagnostic_local/` : `confusion.png`, `score_distributions.png`, `roc.png`, `pr.png`, `confusion.csv`, `differences.csv`, `defect_metrics.csv`, `bootstrap.csv`, `mask_audit.csv`, `roc_points.csv`, `pr_points.csv`, `audit.json`, `preservation.json`. Les liens de figures fonctionnent dans la copie locale ; les PNG ignorés ne seront pas présents dans un clone Git seul.

Conservation vérifiée avant/après : **220 fichiers préexistants identiques par SHA256**, notamment les deux arbres officiels, le premier rapport de suivi et ses sources, les six checkpoints, configurations, sources et manifestes. L'inventaire détaillé est dans `preservation.json`. Aucun entraînement T0/T1/T2 n'a été lancé.
