# A1 v1 — choix fixés avant entraînement complet et avant test

Date : 8 novembre 2026. Étape limitée à l'implémentation, tests et smoke CPU.
Les configurations `ae_improved.yaml` et `train_ae_a1.yaml` définissent ce candidat
initial ; aucune optimalité ou amélioration mesurée sur B0 n'est annoncée.
Aucun score, courbe ou exemple du test B0 n'a été consulté pour choisir les
composants A1. Les fichiers de résultats B0 sont uniquement inventoriés et hachés
pour vérifier leur conservation. Guide §5.2 suivi depuis
`resilientinspect-ai/guide_technique.docx.docx`.

## Architecture

Entrée RGB float32 [B,3,256,256] dans [0,1], même prétraitement que B0.
Encodeur : quatre niveaux Conv3×3 stride2/padding1 sans biais, BatchNorm, ReLU,
puis un bloc résiduel de deux Conv3×3–BatchNorm avec ReLU intermédiaire et après
l'addition. Canaux **32,64,128,256**, latent **[B,256,16,16]**.
Décodeur : nearest ×2, Conv3×3–BatchNorm–ReLU puis bloc résiduel, successivement
128,64,32 canaux, puis nearest ×2, Conv3×3 RGB avec biais et Sigmoid.
BatchNorm conserve les réglages PyTorch utilisés dans B0.

Deux branches encodeur→décodeur seulement, aux résolutions **32×32 et 64×64** :
projection 1×1 sans biais, tanh, multiplication par une constante **0,1**,
addition avant le bloc résiduel du décodeur. Chaque contribution est donc bornée
à ±0,1, avec une échelle sauvegardée comme buffer non entraînable. Aucune skip
128×128 ou RGB 256×256, aucune concaténation directe de l'entrée.
Cela réduit le chemin de copie haute résolution ; **cela ne garantit pas** qu'un
défaut ne sera pas reconstruit. Ce risque devra être analysé lors de l'évaluation
finale, sans optimiser sur ses résultats.

**2 754 371 paramètres entraînables** contre 195 107 pour B0. Architecture,
perte et augmentation sont trois sections indépendantes du YAML. Ablations
prévues : `residual_blocks: false`, `skip_connections: false`, perte L1 seule,
`augmentation.enabled: false`. Chaque future ablation doit avoir sa propre
copie de configuration et être fixée avant test. Une modification de largeur
est possible dans le constructeur mais ne fait pas partie du candidat v1.

## Perte L1 + SSIM, définition et validation numérique

Objectif initial : **0,8 × L1 + 0,2 × (1−SSIM)/2**. L1 moyenne sur tous les
éléments batch/RGB/spatiaux, identique à B0 pour sa composante L1. Le terme
structurel est DSSIM=(1−SSIM)/2 ; les poids portent sur ces deux termes, pas sur
une « SSIM Loss » d'une autre convention.

SSIM mono-échelle, calcul indépendant sur chaque canal RGB puis moyenne sur
canaux, batch et fenêtres ; aucune conversion de luminance ni MS-SSIM.
Fenêtre gaussienne 11×11, sigma=1,5, convolutions séparables en mode valid,
moments population, L=1, K1=0,01 et K2=0,03. Pour mu, variance et covariance
locales, SSIM=(2mu_x mu_y+C1)(2cov+C2) /
((mu_x²+mu_y²+C1)(var_x+var_y+C2)). Les variances négatives d'arrondi sont
ramenées à zéro et SSIM est bornée dans [−1,1]. Pas d'epsilon arbitraire ajouté
aux constantes théoriques déjà strictement positives. Calcul FP32, sans AMP ;
FP64 disponible pour les tests numériques.

Cette définition suit la formule SSIM et ses paramètres classiques ; le traitement
RGB est explicitement notre adaptation. Sources primaires :
[article SSIM](https://eceweb.uwaterloo.ca/~z70wang/publications/ssim.html) et
[paramètres de référence des auteurs](https://www.cns.nyu.edu/~lcv/ssim/ssim_index.m).
Le code PyTorch est une implémentation de la formule, sans ajout de dépendance SSIM.

Validation CPU effectuée avant le smoke réel : comparaison avec un oracle NumPy
2D indépendant (tolérance absolue 1e−12 en FP64), cas constant noir/blanc
analytique, identité, images presque constantes, finitude des gradients et
`torch.autograd.gradcheck`. Cette stabilité numérique locale n'établit ni gain
de détection ni stabilité d'un entraînement complet sur T4.

Comme B0, la perte d'entraînement/validation inclut le letterbox ; SSIM utilise
les fenêtres complètes à l'intérieur de l'image 256×256. Ne pas confondre avec
l'évaluation, qui exclut le padding des scores et métriques. Aucun masque de
défaut n'intervient dans la perte. Pour l'ablation L1 : `loss.name: l1`, poids
1/0, et `training.loss: l1` dans une configuration séparée. Des réglages
contradictoires sont refusés, pas corrigés silencieusement.

La sélection et l'early stopping utilisent **la perte composite val**, sans
augmentation. L1 et DSSIM sont également enregistrées séparément en CSV et
MLflow. Ne pas comparer numériquement une perte composite A1 à la seule L1 B0
comme preuve de supériorité ; la L1 brute est disponible pour un descriptif
commun, et la comparaison de détection attend une évaluation gelée.

## Augmentations réalistes limitées à train/good

Un wrapper autour du Dataset existant applique avec probabilité **0,5** : facteur
de luminosité uniforme [0,9,1,1], puis facteur de contraste uniforme [0,9,1,1].
Contraste centré sur la moyenne RGB des pixels valides après luminosité ;
clipping final [0,1] et padding rétabli à zéro. Géométrie, masques et originaux
inchangés. Aucun flip, rotation, crop, blur, bruit ou défaut synthétique pour ce
premier candidat, pour conserver notamment l'orientation des objets.

L'image augmentée est **aussi la cible** de reconstruction : pas d'objectif de
débruitage ajouté implicitement. Le wrapper refuse val et test, les anomalies et
les chemins de masque. Val utilise le Dataset existant sans transformation
aléatoire. Aucun accès aux masques test, aucune nouvelle statistique de
normalisation. Tirages stateless par seed+epoch×nombre_images+index, indépendants
de la consommation aléatoire du modèle ; l'époque est fixée par la boucle commune.
Workers=0 pour ce candidat, comme B0. Les augmentations ne sortent jamais sur disque.

## Budget et protocole partagé

Mêmes manifestes et splits 80/20 fixés, résolution 256×256, catégories bottle,
hazelnut, leather. Une instance et un Adam indépendants par catégorie. Seed=42,
batch=16, maximum=20 époques, patience=5, min_delta=0, LR=0,001, betas=(0,9;0,999),
eps=1e−8, weight_decay=0, AMP désactivée. Meilleur checkpoint au minimum de la
perte val ; aucun test pour l'architecture, les poids, l'arrêt ou les seuils.
Même budget maximal qu'en B0 ; les époques effectives peuvent varier avec
l'early stopping et le coût par époque est supérieur, sans égalité de temps GPU
présumée.

Pas de nouvelle boucle d'apprentissage : `training.train_ae` prend B0 ou A1 via
`--config`. B0 garde sa classe, sa configuration et sa perte. Checkpoints A1 :
poids/buffers, optimiseur, époque, perte val, variante, catégorie, seed, architecture
complète et configuration effective, empreinte manifeste. Code source et YAML
sauvegardés par run, SHA256 dans la provenance. Le helper de rechargement utilise
l'architecture intégrée au checkpoint, vérifie strictement les poids et l'échelle
des skips ; aucun appel à un YAML courant pour remplacer la structure sauvegardée.
Les options d'ablation sont donc traçables.

Les sorties A1 par défaut sont `artifacts/a1_runs/`, ignorées par Git ; le pipeline
refuse toute sortie dans `artifacts/b0_runs/` ou `reports/evaluation/b0/`.
MLflow conserve la même expérience `resilientinspect-ae` avec tag variant=A1.
Courbes et paramètres affichent explicitement la variante et la perte utilisée.

Smoke : CPU, bottle, batch=2, **une époque et au plus deux mini-batches par split**.
L'entraînement complet A1 sur CPU est bloqué ; le run complet reste à lancer sur
Kaggle après validation. Les tests d'intégration entraînent seulement des images
synthétiques temporaires, jamais le dataset officiel complet.

## Compatibilité et évaluation future

Aucune dépendance ajoutée ; opérations PyTorch standard compatibles avec le
contrat Python >=3.11,<3.14. Pas de torchvision, paquet SSIM ou installation
automatique. Sur Kaggle utiliser les extras `train,eda,eval,dev` sous les
contraintes du runtime existant, jamais `data` qui impose le PyTorch CPU local.
La procédure README conserve les versions Torch/CUDA préinstallées. CUDA
explicite indisponible = erreur, aucun repli silencieux.

Déterminisme comme B0 : seeds, algorithmes déterministes stricts, cuDNN benchmark
désactivé, FP32. PyTorch documente des restrictions de reproductibilité suivant
les opérations et périphériques, notamment
[interpolate 2.11](https://docs.pytorch.org/docs/2.11/generated/torch.nn.functional.interpolate.html).
Python 3.13/PyTorch 2.11.0+cu130/Tesla T4 et la mémoire batch16 restent à vérifier
réellement ; un test CUDA forward/backward est prévu et ignoré localement.

Pour la comparaison future, **conserver le protocole de score/seuillage B0**
existant : carte L1 RGB sans lissage, top-1 % image, quantiles val normale 95 %
image et 99,5 % pixel, méthode higher, décision strictement >, padding exclu.
La carte d'anomalie reste L1 même si la perte d'entraînement ajoute SSIM.
**Recalibrer les seuils numériques sur val normale pour chaque modèle A1** ; ne
pas réutiliser les valeurs numériques des seuils B0 ni maximiser F1/Dice/IoU test.
L'implémentation d'évaluation A1 et son exécution ne font pas partie de cette
étape. Les limites de réemploi de val pour sélection et calibration restent
applicables. Aucun test A1 officiel avant nouvelle validation.

Les empreintes figées, commandes, tests et résultats réellement observés sont
consignés dans `a1_implementation_verification.json` et le journal des décisions.
