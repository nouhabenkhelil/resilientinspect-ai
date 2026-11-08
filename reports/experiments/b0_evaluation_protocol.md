# B0 — protocole d'évaluation proposé, 8 novembre 2026

**Statut : implémenté pour revue ; protocole non encore validé par l'utilisatrice.**
Aucune calibration sur MVTec ni évaluation du test officiel n'est exécutée à
cette étape. Les seuls rapports de métriques et figures produits par les tests
utilisent des images et checkpoints synthétiques temporaires, sans entraînement.
Les seuils numériques réels seront calculés après validation du protocole.

## Périmètre et provenance

Un B0 indépendant par catégorie, dans l'ordre bottle, hazelnut, leather.
Le modèle, les poids, les configurations d'entraînement, les manifestes et le
prétraitement existants sont conservés. Le manifeste complet est contrôlé contre
`preparation.json`. Les originaux sont ouverts en lecture seulement, leur SHA256
est contrôlé par le Dataset avant utilisation. Pas d'augmentation ni de nouvelle
normalisation ; RGB float32 dans [0,1], letterbox 256×256, RGB bilinéaire et masque
binaire au plus proche voisin. Aucun export à la résolution native n'est impliqué.

La sélection automatique parcourt `artifacts/b0_runs/<catégorie>/full_*/best.pt` :
run terminé, scope full, B0, sélection val, test_used=false, aucune limitation
smoke de mini-batches. Les métadonnées, l'époque, la somme SHA256 et la structure
des poids sont vérifiées. Chargement `weights_only=True`, strict, poids finis,
`eval()`, `inference_mode()`, gradients désactivés ; aucun optimiseur exécuté.
Les dossiers smoke et les copies `mlartifacts`/`mlruns` sont exclus. Des copies
canoniques de même SHA256 sont dédupliquées. Plusieurs checkpoints complets
distincts pour une catégorie provoquent un arrêt : aucun classement automatique
par performance test, date ou nom de fichier.

## Carte et score fixés avant calibration

Pour chaque pixel : **E(h,w) = mean_c |x(c,h,w) − reconstruction(c,h,w)|**.
Carte brute float32 entre 0 et 1, sans lissage, normalisation min/max par image,
seuillage préalable ou morphologie. Le padding identifié par `valid_mask=0` est
exclu des scores, de la calibration et de toutes les métriques pixel.

Pour N pixels valides, **K = ceil(0,01 × N)** et **score image = moyenne des K
plus grandes erreurs** (accumulation float64). Pour une image carrée, N=65536
et K=656. Il s'agit d'un score d'erreur, pas d'une probabilité.

Le guide §5.1 évoque une carte lissée, et §5.4 une ablation avec/sans lissage.
La proposition ici est de commencer par le cas sans lissage, filtre identité,
afin de mesurer la reconstruction brute sans introduire un noyau supplémentaire.
**Cet arbitrage reste à valider avant l'évaluation officielle**, comme K=1 % et
les deux quantiles. Aucune recherche de ces paramètres sur le test n'est prévue.

## Calibration par catégorie, exclusivement sur val normale

- Seuil image : quantile empirique **95 %** de tous les scores image val.
- Seuil pixel : quantile empirique **99,5 %** de toutes les erreurs des pixels
  valides des images val, regroupées ; pondération par pixel, pas par image.
- NumPy `quantile(method="higher")` : observation ordonnée d'indice
  `ceil(q × (n−1))`, sans interpolation entre observations.
- Décision image ou pixel : **score > seuil**. L'égalité est négative.
- La calibration rejette un split autre que val, un label anormal, une provenance
  autre que train officiel, ou un chemin de masque. Elle ne lit que les images
  val de la catégorie demandée, jamais les images/masques test.

Les taux de dépassement empiriques sur val sont enregistrés comme contrôles de
calibration. Ils ne prouvent ni un taux futur de faux positifs de 5 %/0,5 %, ni
une performance de détection. Les petits effectifs de validation et la dépendance
spatiale des pixels limitent cette interprétation. Le même val a déjà servi à
sélectionner le meilleur checkpoint : la calibration n'est donc pas une
validation indépendante et peut être optimiste. Pas de découpage supplémentaire
introduit après coup.

`calibration.json` conserve les seuils, effectifs, scores val, environnement et
empreintes du protocole YAML, checkpoint, manifeste, code d'évaluation et Dataset.
Un fichier compagnon `calibration.sha256` contrôle son intégrité à la relecture.
Une calibration périmée, modifiée ou incompatible bloque l'inférence test.
Le fichier est figé à la première écriture : aucun résultat différent n'est écrasé.

## Évaluation finale, après accord explicite uniquement

La commande par défaut `--stage inspect` vérifie les checkpoints sans construire
de Dataset ni effectuer d'inférence. Le stage `calibrate` est réservé à val.
Le stage `evaluate` exige `--approved-protocol-sha256` égal au SHA256 complet du
YAML revu et une calibration compatible par catégorie, avant de construire le
Dataset test. Cet argument matérialise le protocole approuvé ; il ne constitue
pas, à lui seul, une preuve d'approbation humaine. Il n'a pas été fourni pour
le dataset réel durant cette implémentation.

Une fois l'accord reçu, tout le test officiel est évalué sans changement de split.
Les labels et masques servent alors uniquement aux métriques finales. Aucun seuil
n'est ajusté, aucun meilleur Dice/IoU/F1 n'est recherché. Ne pas modifier le
protocole après observation du test pour améliorer ses résultats.

## Métriques et conventions

La classe positive est anomalie=1. Les AUROC/AP utilisent les scores continus
bruts, jamais les décisions seuillées. Implémentations exactes scikit-learn
1.8.0, traitement des ex æquo inclus ; AP non interpolée, pas aire trapézoïdale
sous une courbe PR. Sources : [AUROC](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.roc_auc_score.html),
[Average Precision](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html).

- **Image :** AUROC, AP, effectifs normaux/anormaux, TN/FP/FN/TP et F1 avec le seuil
  val image. Aucun choix de seuil par une courbe test.
- **Pixel :** AUROC/AP sur tous les pixels valides de la catégorie, images normales
  incluses. Leurs faux positifs comptent. Résolution d'évaluation 256×256.
- **Segmentation primaire :** agrégation micro de TP/FP/FN sur tous les pixels
  valides test de la catégorie : Dice=2TP/(2TP+FP+FN), IoU=TP/(TP+FP+FN).
- **Descriptif secondaire :** moyenne Dice/IoU par image anormale, avec nombre
  d'images ayant une valeur définie. Les normales ne gonflent pas cette moyenne.
- Si une cible et sa prédiction sont vides, Dice/IoU sont `null`, pas 1. Les
  images anormales dont le masque est vide après redimensionnement sont signalées.
- Si une population ne contient pas les deux classes, AUROC **et AP** sont
  `null` avec `both_classes_required` (convention explicite, même si une AP peut
  être définie dans certains cas dégénérés).
- Agrégation globale : moyenne macro non pondérée des métriques par catégorie,
  avec nombre de catégories définies. Pas d'AUROC globale mélangeant des scores
  issus de modèles différents. Aucun AUPRO, intervalle de confiance ou résultat
  de latence ne sera présenté comme calculé par ce module.

## Rapports, figures et reproductibilité

Sorties locales `reports/evaluation/b0/<SHA-protocole[:12]>/<catégorie>/` :
`calibration.json`, `calibration.sha256`, `calibration_scores.csv`, `predictions.csv`, `metrics.json`,
`figures/*.png`. Tableau intercatégories `category_metrics.csv`, résumé macro
`macro_metrics.json`, inventaire `checkpoint_inventory.json` à la racine du run.
CSV de prédictions : chemins relatifs, labels, défaut, score, seuils, décision,
pixels valides et TP/FP/FN/Dice/IoU. JSON : provenance et conventions traçables.
Les sorties d'évaluation sont entièrement ignorées par Git ; aucune publication.

Une figure par type de défaut et pour good, première image par ordre lexical,
choisie sans consulter les scores : entrée RGB prétraitée, reconstruction,
heatmap brute avec échelle fixe [0,1], masque GT nearest. Catégorie, split et
identifiant du run figurent dans le titre. Les figures ne prétendent pas montrer
les cas extrêmes ni représenter tous les modes d'échec. La carte d'erreur n'est
pas une explication Grad-CAM.

Seed=42, inférence FP32, pas d'AMP, pas de shuffle, workers=0, algorithmes PyTorch
déterministes et réglages cuDNN identiques à l'entraînement. Un périphérique CUDA
demandé mais indisponible est refusé. Un GPU différent, une version de bibliothèque
ou une taille de batch différente peuvent produire des écarts numériques ; aucune
identité bit à bit CPU/CUDA n'est annoncée. Les tests vérifient deux exécutions CPU
sur le même environnement synthétique. Python 3.13/CUDA/T4 reste à vérifier
réellement ; l'extra `eval` n'impose ni ne remplace PyTorch.

Les résultats réels de vérification de cette implémentation sont consignés dans
`b0_evaluation_verification.json` et `decision_log.md`. Le passage au test officiel
attend la revue de ce document et de `configs/evaluate_ae_b0.yaml`.
