# Évaluation A1 — protocole à revoir avant exécution officielle

Date : 9 novembre 2026. Cette étape implémente et teste l'évaluation ; elle
n'autorise ni ne lance la calibration réelle ou le test officiel A1.
Les tests d'intégration utilisent exclusivement des images et des poids
synthétiques temporaires. Aucun réentraînement des modèles réels.

## Contrat scientifique commun à B0 et A1

Le module `src/evaluation/evaluate_a1.py` lit directement
`configs/evaluate_ae_b0.yaml`, sans créer de configuration divergente.
SHA256 du fichier revu :
`f515662ab4ef0437194f7fdc7b57c8ea435ae6cb7e1be95c26476a91fa5d963e`.

Les fonctions `anomaly_maps`, `image_score`, `valid_values`,
`calibrate_records`, `infer_records`, `ranking_metrics`, `overlap_metrics`
et `summarize_records` sont celles du module B0 inchangé. Le chargement du
modèle est spécifique à A1 et passe par
`src/training/a1_config.py::load_a1_checkpoint()`, à partir de l'architecture
embarquée, sans remplacement par des hyperparamètres courants.

| Élément | Contrat fixé |
| --- | --- |
| Entrée | RGB float32 [0,1], letterbox 256×256, bilinear ; masque nearest |
| Carte | Moyenne RGB des erreurs absolues L1, sans SSIM ni lissage |
| Pixels | Padding exclu par `valid_mask`, normales incluses dans les métriques pixel |
| Score image | Moyenne des `ceil(0,01 × N_valides)` valeurs les plus élevées |
| Seuil image | Quantile 95 % des scores de validation normale, méthode `higher` |
| Seuil pixel | Quantile 99,5 % de tous les pixels valides de validation normale, `higher` |
| Décision | Score strictement supérieur au seuil correspondant |
| Inférence | FP32, aucun AMP, batch 4, workers 0, sans shuffle ni augmentation |
| Reproductibilité | Seed 42, deux threads CPU, algorithmes PyTorch déterministes |

Chaque modèle A1 recalcule ses **propres seuils numériques**, exclusivement sur
sa validation normale issue de `train/good`. Aucune lecture des calibrations B0
dans le pipeline A1, aucun seuil ou hyperparamètre choisi sur test. Les données
de validation ont aussi servi à sélectionner le checkpoint ; les faux positifs
de calibration sont descriptifs, sans garantie de généralisation.

AUROC/AP image et pixel utilisent les scores continus. F1 image utilise le seuil
val image. Dice/IoU primaires agrègent les TP/FP/FN pixel en micro ; moyennes
secondaires sur images anormales seulement. Les cas vide/vide donnent `null`.
Une population à classe unique donne AUROC/AP `null` avec raison explicite.
La synthèse intercatégories est une moyenne macro non pondérée, sans mélanger
les scores de modèles distincts dans une AUROC globale. Ces conventions sont
strictement celles de `reports/experiments/b0_evaluation_protocol.md`.

## Checkpoints inspectés sur CPU

| Catégorie | Run complet sélectionné | Meilleure époque / réalisées |
| --- | --- | --- |
| bottle | `03f6c284b0164105bf364181695ce3b5` | 15 / 20 |
| hazelnut | `0966957370a14cdda9d65a15e54cbaa5` | 17 / 20 |
| leather | `41e6a12c4b4942b6b7d6dc9e1ea3720a` | 18 / 20 |

Deux runs smoke et cinq copies MLflow sont exclus avant chargement des poids.
Une catégorie absente ou plusieurs checkpoints distincts échouent sans choix
silencieux. Les trois modèles ont chacun 2 754 371 paramètres et se chargent
strictement sur CPU, en mode eval, gradients désactivés, poids finis.

Contrôles : empreintes checkpoint/manifeste, statut completed/full/A1,
catégorie/run/seed, absence de limitation de batches, sélection val et
`test_used=false`, cohérence époque/perte/historique et configurations
embarquées. Les copies d'architecture, provenance, code source et usages
train/val archivés sont vérifiés lorsqu'ils sont présents ; ils sont tous
présents pour les trois runs locaux. Les usages déclarés restent disjoints,
normaux et sans test. L'inspection n'ouvre aucun Dataset, image ou masque.

Inventaire détaillé :
`reports/evaluation/a1/f515662ab4ef/checkpoint_inventory.json`.

## Trois commandes distinctes

Depuis la racine du dépôt, sur l'environnement CPU existant :

```powershell
# Déjà exécuté : métadonnées et chargement des poids, sans inférence.
& .\.venv\Scripts\python.exe -m resilientinspect.evaluation.evaluate_a1 --stage inspect --device cpu

# À exécuter après revue : uniquement validation normale des trois modèles.
& .\.venv\Scripts\python.exe -m resilientinspect.evaluation.evaluate_a1 --stage calibrate --device cpu

# À exécuter seulement après validation explicite du SHA du protocole.
& .\.venv\Scripts\python.exe -m resilientinspect.evaluation.evaluate_a1 --stage evaluate --device cpu --approved-protocol-sha256 "SHA256_EXPLICITEMENT_VALIDE"
```

Le jeton d'exemple de la troisième commande est volontairement invalide.
La revue doit porter sur ce document, le YAML et le code ; l'utilisateur fournit
ensuite explicitement le SHA complet approuvé dans l'option. Sans cette option,
ou avec un SHA différent, le programme refuse avant le manifeste, les
checkpoints et la construction du Dataset test. Aucune approbation automatique
ni passage implicite de calibration à évaluation.

Avant le premier test, les calibrations des **trois catégories** doivent être
présentes, intègres et compatibles avec leurs checkpoints, manifeste, protocole,
code scientifique/chargement/dataset et environnement d'exécution. Une
calibration B0 est refusée. Un changement de ces éléments exige une nouvelle
calibration dans un dossier de sortie neuf. Le protocole ne doit pas être
ajusté d'après les résultats test.

Les options de chemins `--root`, `--manifest`, `--runs-root`, `--protocol` et
`--output-dir` restent disponibles ; valeurs par défaut identiques aux chemins
locaux du projet, avec runs `artifacts/a1_runs` et sorties
`reports/evaluation/a1`. Les données, manifestes, checkpoints et destinations
B0 sont protégés ; les liens/jonctions ne doivent pas contourner ces contrôles.
Les fichiers de sortie existants différents ne sont jamais écrasés.

## Sorties prévues et comparaison

Sous `reports/evaluation/a1/<SHA-protocole[:12]>/<catégorie>/` :

- `calibration.json`, `calibration.sha256`, `calibration_scores.csv` ;
- `metrics.json`, `predictions.csv`, `predictions.json` ;
- `figures/*.png` : entrée RGB prétraitée, reconstruction, heatmap brute
  d'échelle fixe [0,1], masque GT, masque prédit au seuil val. Le padding est
  masqué sur heatmap/masques. Une image par défaut et pour good, première par
  ordre lexical, choisie sans utiliser ses scores.

À la racine du run : `category_metrics.csv`, `macro_metrics.json` et inventaire.
Les résultats réels de calibration, prédictions, métriques et figures A1
**n'existent pas encore à cette étape**. Les sorties d'évaluation restent
ignorées par Git et locales.

Le tableau préparé dans `reports/evaluation/a1/comparison/comparison.csv`
(et JSON avec provenance SHA des sources) lit les résultats B0 existants.
Ses lignes A1 sont `pending`, valeurs vides/`null`, jusqu'à l'évaluation réelle.
Aucun score estimé. Les SHA protocole/manifeste/dataset doivent correspondre.
Après l'évaluation officielle, générer un **nouveau** tableau sans écraser celui
de préparation :

```powershell
& .\.venv\Scripts\python.exe -m resilientinspect.evaluation.compare_b0_a1 --b0-dir reports/evaluation/b0/f515662ab4ef --a1-dir reports/evaluation/a1/f515662ab4ef --output-dir reports/evaluation/a1/comparison_after_evaluation
```

## Vérification et limites

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -W error --tb=short
& .\.venv\Scripts\python.exe -m pip check
```

Les tests synthétiques couvrent les calculs communs, le chargement A1 strict,
la calibration val seule avec garde sur ouverture des images, le refus avant
test sans approbation ou avec calibration périmée, le pipeline trois catégories,
la conservation des poids/buffers/gradients et la reproductibilité CPU des
seuils, scores, métriques et PNG. Les comparaisons ne modifient pas leurs sources.
Les tests existants de B0 restent exécutés.

Les preuves d'exécution et de conservation sont dans
`reports/experiments/a1_evaluation_verification.json` et leurs artefacts locaux
sous `reports/evaluation/a1/`. Aucun changement de poids, résultats,
configurations ou code B0. Les garanties de reproductibilité concernent le même
environnement CPU ; aucune identité bit à bit entre CPU/CUDA ou versions de
bibliothèques différentes n'est annoncée.

Résultat final : **343 tests réussis, 2 ignorés** (tests CUDA B0/A1 sur cette
machine CPU), avec warnings traités en erreurs. Les 73 nouveaux cas synthétiques
A1/comparaison réussissent, y compris les jonctions Windows. `pip check` réussit.
La figure synthétique à cinq panneaux a aussi été inspectée visuellement.
Les SHA256 des **451 fichiers préexistants** contrôlés restent identiques :
157 fichiers de runs B0, 236 de runs A1, 34 résultats B0, 6 configurations et
18 fichiers source. Les inventaires des runs et résultats préexistants sont
également inchangés ; le manifeste conserve son empreinte figée.

**Arrêt pour revue : aucune calibration réelle ni évaluation officielle A1.**
