# Portabilité de l'évaluation T0/T1/T2

## Politique fixée avant la validation CPU

Le 17 novembre 2026, la comparaison par égalité des versions de Python,
PyTorch, NumPy, torchvision et scikit-learn est remplacée par un contrôle de
compatibilité suivi d'une validation numérique complète. Les versions Kaggle
restent conservées dans `environment.json` et dans la calibration originale.
Les rapports contiennent séparément ces métadonnées, l'environnement Windows
courant et les changements de versions. Pillow, OS, architecture machine,
threads, déterminisme et précision des multiplications sont aussi tracés
localement. Les informations absentes des archives Kaggle restent absentes.

Les changements de version majeure des cinq bibliothèques contrôlées sont
refusés. Les changements mineurs, correctifs et suffixes CUDA/CPU sont admis à
l'inspection, puis soumis à la parité. Un changement de version mineure de
torchvision 0.x exige également cette validation. Le modèle est chargé par
l'API existante, avec `weights_only=True`, `strict=True`, mode eval, poids
finis et vérification supplémentaire de l'identité des types, dimensions et
valeurs des tenseurs après chargement. Aucun poids ImageNet n'est téléchargé.

La politique `transfer_fp32_cpu_v1` est figée dans le module, sans option CLI
permettant d'élargir les tolérances. Pour chaque score sigmoid archivé `s`, le
score CPU `c` doit être fini, dans [0,1], et respecter

```text
abs(c - s) <= 1e-5 + 1e-4 * abs(s)
```

Cette enveloppe FP32 autorise une petite accumulation d'arrondis entre kernels
CUDA/CPU et versions, tout en bornant l'écart absolu à 0,00011 pour des
probabilités dans [0,1]. Elle est choisie avant le premier recalcul local et
doit rester identique pour les neuf runs. Toute violation bloque le test.

Les décisions appliquent toujours `score > seuil_Kaggle`. Chaque changement
est enregistré individuellement. Un changement est admis uniquement si les
deux scores se trouvent à une distance absolue maximale de `1e-5` du seuil
Kaggle original et si la parité du score est respectée. Ce cas de frontière
couvre notamment le score normal ayant fixé le quantile `higher`, exactement
égal au seuil sur Kaggle. Toute autre inversion bloque le test. Aucun seuil
n'est recalculé à partir des scores CPU. Le quantile des scores Kaggle est
seulement revérifié à l'inspection.

## Intégrité et séparation des étapes

Les SHA256 du checkpoint sont contrôlés avant désérialisation. Les SHA256 de
la calibration, de la configuration effective, du plan et du manifeste restent
stricts. Le plan doit être identique à sa reconstruction depuis les seules
métadonnées train/val. Les onze sources et configurations enregistrées dans
`provenance.json` doivent correspondre à `summary.json`, à leurs copies
archivées sous `source/` et aux fichiers locaux utilisés. Le contrôle porte
sur les octets exacts, y compris les fins de ligne.

`inspect` vérifie les métadonnées et le chargement des poids sans construire
de Dataset et sans ouvrir d'image. Un succès indique que la validation
numérique peut commencer.

`validate` reconstruit exclusivement `SyntheticAnomalyDataset(split="val")`
avec le plan archivé, vérification SHA des sources activée, batch 4, deux
threads, FP32, sans AMP et algorithmes déterministes. Il réutilise `run_epoch`
en mode validation, sans optimiseur. Chaque sample_id, chemin, split et label
est rapproché des scores archivés. Toutes les recettes de validation de la
catégorie doivent être présentes exactement une fois. Les images physiques
proviennent du `train/good` officiel affecté au split val. Le manifeste global
est lu comme métadonnées. Aucune image ni masque test officiel n'est ouvert.
Le rapport `compatibility.json` contient les scores comparés, leurs écarts,
les changements de décision, la politique, les environnements et les SHA du
code d'évaluation et du protocole. Un échec numérique produit un rapport
`failed` et un code retour 1.

`evaluate` exige toujours `--approved-protocol-sha256` exact avant l'accès au
run ou au manifeste. Il réexécute ensuite tous les contrôles et la validation
CPU avant de construire le Dataset test. Cette nouvelle validation évite de
réutiliser un rapport devenu périmé. Le rapport officiel inclut la preuve de
parité. L'évaluation officielle est limitée au CPU dans cette phase.

## Commandes Windows depuis la racine du projet

Ces commandes sélectionnent les neuf runs full seed42 et refusent les
doublons ou catégories manquantes. Les smoke et les copies MLflow sont exclus.

```powershell
$python = ".\.venv\Scripts\python.exe"
$runs = @(
    foreach ($variant in @("T0", "T1", "T2")) {
        foreach ($category in @("bottle", "hazelnut", "leather")) {
            $matches = @(Get-ChildItem -LiteralPath "artifacts/transfer_runs/$variant/$category/seed42" -Directory -Filter "full_*")
            if ($matches.Count -ne 1) { throw "Un unique run full requis pour $variant/$category" }
            $matches[0].FullName
        }
    }
)
foreach ($run in $runs) {
    & $python -m resilientinspect.evaluation.evaluate_transfer --stage inspect --run-dir $run --device cpu
    if ($LASTEXITCODE -ne 0) { throw "Inspection refusee pour $run" }
}
foreach ($run in $runs) {
    & $python -m resilientinspect.evaluation.evaluate_transfer --stage validate --run-dir $run --device cpu --output-dir reports/transfer/portability
    if ($LASTEXITCODE -ne 0) { throw "Validation refusee pour $run" }
}
```

Les chemins par défaut sont `data/manifests/manifest.csv` et
`data/raw/mvtec_ad`. Adapter `--manifest` et `--root` ensemble si nécessaire.
Les rapports sont écrits sans écrasement sous
`reports/transfer/portability/<variante>/<catégorie>/seed42/<SHA_checkpoint_12>/<SHA_protocole_12>/compatibility.json`.

Les tests de régression utilisent exclusivement des images et checkpoints
temporaires fabriqués sans entraînement. La commande suivante les exécute.

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_transfer_evaluation.py tests/test_transfer_model.py tests/test_transfer_training.py tests/test_synthetic.py -q -W error --tb=short
```

L'arrêt demandé intervient après `validate`. Aucune commande d'évaluation
officielle n'est exécutée pendant cette préparation.

## Résultats de la validation du 17 novembre 2026

Les neuf inspections et neuf validations CPU ont réussi avec la politique
ci-dessus. Les 1 020 comparaisons couvrent intégralement la validation
synthétique des neuf modèles. Les lectures d'images ont été protégées dans
le processus de validation par des gardes sur `builtins.open` et `io.open`,
limitées aux chemins des sources val archivées sous la racine des données.
Les 170 sources normales distinctes ouvertes proviennent de `train/good`.

| Variante | Catégorie | Scores | Écart absolu maximal | Décisions modifiées |
| --- | --- | ---: | ---: | ---: |
| T0 | bottle | 84 | 6,855 × 10⁻⁷ | 1 |
| T0 | hazelnut | 158 | 1,103 × 10⁻⁶ | 0 |
| T0 | leather | 98 | 1,804 × 10⁻⁹ | 0 |
| T1 | bottle | 84 | 2,086 × 10⁻⁶ | 1 |
| T1 | hazelnut | 158 | 2,623 × 10⁻⁶ | 1 |
| T1 | leather | 98 | 4,172 × 10⁻⁷ | 1 |
| T2 | bottle | 84 | 1,192 × 10⁻⁷ | 1 |
| T2 | hazelnut | 158 | 2,444 × 10⁻⁶ | 1 |
| T2 | leather | 98 | 1,192 × 10⁻⁷ | 1 |

Les sept inversions concernent chacune un exemple normal dont le score
Kaggle était exactement égal au seuil original. Son score CPU est très
légèrement supérieur au seuil, avec des écarts compris entre 6,403 × 10⁻¹⁰
et 6,109 × 10⁻⁷. La décision stricte passe donc de 0 à 1. Ces cas respectent
la règle de frontière fixée avant exécution. Aucun écart de score hors
tolérance ni changement de décision injustifié n'a été observé. Tous les
seuils originaux sont conservés.

L'environnement Kaggle archivé utilise Python 3.13.16, torch 2.11.0+cu130,
torchvision 0.26.0+cu130 et NumPy 2.1.3 sur Tesla T4. La validation locale
utilise Python 3.11.9, torch 2.15.0+cpu, torchvision 0.29.2+cpu et NumPy 2.3.5
sur Windows AMD64, avec scikit-learn 1.8.0 dans les deux environnements.

Les preuves locales sont disponibles sous `reports/transfer/portability/`.

- `inspections.json` conserve les neuf inspections sans ouverture d'image.
- `validation_summary.json` référence les neuf rapports et leurs SHA256.
- Les neuf fichiers `compatibility.json` détaillent chaque score et décision.
- `protected_integrity.json` vérifie l'identité SHA256, taille et date de
  914 fichiers préexistants, dont les runs B0/A1/transfert, leurs résultats
  sous `reports/evaluation`, les configurations, manifestes et cinq modules
  dont la modification était interdite. Aucun ajout ni retrait n'a été
  constaté dans ces répertoires protégés.

La suite complète passe avec `512 passed, 2 skipped`, warnings traités en
erreurs. Les deux cas ignorés nécessitent CUDA et concernent les anciens
tests B0/A1. `pip check` et `git diff --check` réussissent également. Les
47 cas ajoutés portent sur la portabilité, les empreintes, les types et
dimensions des poids, la parité, les décisions à la frontière et la non-fuite.
