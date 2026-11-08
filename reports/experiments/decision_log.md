# Journal des décisions et preuves

## 2026-11-06 — Phase 0 uniquement

**Objectif.** Préparer un dépôt testable sous Windows 11 et Python 3.11, avant
toute manipulation de MVTec AD et toute expérience Deep Learning.

**Référence.** Guide technique v1.0 lu intégralement depuis le fichier fourni
`resilientinspect-ai/guide_technique.docx.docx`. Le chemin annoncé
`docs/guide_technique.docx` n'existe pas au moment de la lecture. Sections 11,
15 et 16 appliquées : arborescence cible, tâches bornées, preuves réelles,
commandes PowerShell et validation avant la phase suivante.

| Décision | Motif et statut |
| --- | --- |
| Phase 0 seulement | Aucun pipeline, modèle, entraînement, métrique, DVC, MLflow, API ou CI actif. |
| Trois catégories candidates | `hazelnut`, `bottle`, `leather` provisoires ; aucune catégorie confirmée. |
| Python 3.11 x64 | Le `.venv` existant fonctionne en 3.11.9 ; il est conservé. |
| Interpréteur explicite | L'alias Windows `python` échoue ; le lanceur `py -0p` ne référence que Store 3.13. |
| CPU provisoire | GPU AMD intégré détecté, aucun NVIDIA déclaré ; ne pas supposer CUDA. |
| PyTorch différé | Absent lors de l'audit ; installation non requise pour le socle et aucun runtime CUDA imposé. |
| Dépendances minimales | PyYAML pour la configuration, pytest pour les tests ; versions directes fixées. |
| Chemins du guide | Modules physiques `src/data`, etc. ; paquet importable `resilientinspect` via setuptools. |
| Composants futurs réservés | Dossiers/docstrings seulement, sans faux fichiers exécutables ni résultats. |
| Données et poids hors Git | Données, artefacts, checkpoints, archives, caches et secrets exclus ; marqueurs vides seuls admis. |

### Audit réellement observé

| Contrôle | Preuve / résultat |
| --- | --- |
| Python du projet | `.venv\Scripts\python.exe` : Python 3.11.9, 64 bits. |
| Git | `git --version` : 2.53.0.windows.1 ; dépôt `master` initialement sans commit. |
| Paquets à l'arrivée | pip 26.3, setuptools 65.5.0 ; PyYAML, pytest, torch et torchvision absents. |
| CPU | `Get-CimInstance Win32_Processor` : AMD Ryzen 5 5500U with Radeon Graphics, 6 cœurs / 12 threads. |
| RAM | `Win32_ComputerSystem.TotalPhysicalMemory` : 7 895 982 080 octets (~7,35 Gio). |
| GPU | `Win32_VideoController` : AMD Radeon(TM) Graphics, pilote 31.0.12016.9. |
| Mémoire GPU déclarée | WMI : 536 870 912 octets (512 Mio), sans mesure de toute la mémoire partagée. |
| NVIDIA | Aucun GPU NVIDIA déclaré par CIM ; `Get-Command nvidia-smi` ne trouve rien. |
| CUDA / PyTorch | Non testé : PyTorch absent. Aucun gain GPU ni compatibilité DL affirmé. |

Les lectures matérielles CIM ont d'abord été refusées par la sandbox, puis ont
réussi avec l'autorisation d'exécution nécessaire. Le nom de version noyau
`Windows-10-10.0.26200-SP0` retourné par Python ne suffit pas à identifier
l'édition commerciale de Windows.

### Vérifications du socle

| Commande / contrôle exécuté | Résultat réel |
| --- | --- |
| Analyse du TOML et AST Python | `pyproject.toml`, `scripts/smoke_test.py`, `tests/test_smoke.py` valides. |
| Analyse syntaxique PowerShell 5.1 | `scripts/bootstrap.ps1` valide. |
| Bootstrap normal | Réutilise le `.venv` Python 3.11 x64 ; installation éditable réussie, code de sortie 0. |
| `python -m pip check` via `.venv` | `No broken requirements found.` ; code 0. |
| `python scripts/smoke_test.py` via `.venv` | `status: ok`, tous les répertoires présents, paquet 0.0.1 importé, configuration provisoire valide ; code 0. |
| `python -m pytest -q` via `.venv` | **17 passed in 1.36s** ; code 0. |
| CLI et imports hors projet | Vérifiés par les tests avec Python `-I`, sans ajout de `PYTHONPATH`. |
| Dataset absent | Validation testée avec une racine inexistante, sans création ni lecture de données. |
| Exclusions Git | Tests réussis pour données, checkpoints et secrets ; `.env.example` et marqueurs autorisés. |
| Inspection des données/artefacts | `data/` et `artifacts/` contiennent uniquement des `.gitkeep` de 0 octet. |
| État Git final du socle | Aucun fichier suivi ni commit créé ; `.venv`, cache de test et audit JSON sont ignorés. |

Le lancement direct d'un fichier `.ps1` était initialement bloqué par la
stratégie d'exécution Windows. Le bootstrap a été lancé dans un processus enfant
avec `powershell -NoProfile -ExecutionPolicy RemoteSigned -File
.\scripts\bootstrap.ps1`, sans modification persistante de la stratégie.
L'installation PyPI a d'abord échoué dans la sandbox (`WinError 10013`), puis
a réussi lors de la relance autorisée hors sandbox.

La première exécution pytest donnait 16 réussites et un échec du test Git :
Windows convertissait les séparateurs LF en CRLF dans l'entrée texte de
`git check-ignore`. Le test utilise désormais une entrée binaire et le mode NUL
(`-z`), puis les 17 tests ont réussi. Aucun résultat d'entraînement n'est concerné.

La preuve machine réelle est sauvegardée dans
`reports/experiments/environment_audit.json`, ignorée par Git, horodatée
`2026-11-06T11:18:14.426134+00:00` (12:18 à Africa/Lagos). PyTorch y reste
`not_installed` et `cuda_available` vaut `null`.

Paquets observés après installation : projet 0.0.1, PyYAML 6.0.3, pytest 9.2.0,
colorama 0.4.6, iniconfig 2.3.1, packaging 26.3, pluggy 1.7.0, Pygments 2.21.0,
pip 26.3 et setuptools 65.5.0. Le backend setuptools 80.9.0 fixé dans
`pyproject.toml` a été utilisé dans l'environnement de construction isolé de pip.

Un nettoyage facultatif des dossiers vides créés avant lecture du guide a été
refusé ; ces dossiers sont conservés sans contenu et sans fichier suivi par Git.

### Vérification isolée du bootstrap

Des copies identiques au script source ont été exécutées dans un répertoire
temporaire ignoré sous `.pytest_cache/`, sans modifier le `.venv` principal :

| Scénario exécuté | Résultat réel |
| --- | --- |
| Création avec `-PythonPath` explicite et `-SkipInstall` | Code 0 ; nouvel interpréteur sondé : `3.11.9;64`. |
| Réutilisation depuis un autre répertoire courant | Code 0. |
| `.venv` existant sans `Scripts/python.exe` | Refus, code 1 ; marqueur conservé, SHA256 identique. |
| Installation éditable dans un projet temporaire sans métadonnées | Échec pip attendu, code 1 propagé par le bootstrap ; `PIP_NO_INDEX=1` empêche l'accès aux index. |
| Stratégies d'exécution persistantes | Toutes restent `Undefined` après les tests. |

Preuves locales conservées dans
`.pytest_cache/bootstrap-validation-da479c6ac36a4910807db7659e354eb5/results.json`
et les logs voisins ; répertoire confirmé ignoré par Git. Les chemins alternatifs
de recherche de Python et le cas d'un exécutable de mauvaise version n'ont pas
été exécutés. Le premier harnais a été interrompu par la gestion PowerShell des
erreurs stderr attendues ; les deux scénarios d'échec ont ensuite été rejoués
avec capture explicite et validés.

### Limites et prochain point de validation

Le dataset n'a pas été téléchargé ni inspecté. Aucun effectif, split, checksum,
score ou benchmark de modèle n'est disponible. Les versions directes sont fixées,
mais aucun verrou transitif complet de l'environnement DL n'est encore établi.
L'absence de PyTorch empêche la validation tensorielle et CUDA à ce stade.
La création explicite et la réutilisation d'un environnement ont été testées
séparément, comme décrit ci-dessus.

**Arrêt avant phase 1.** Attendre la validation explicite de l'utilisateur ;
aucune autorisation de téléchargement, pipeline de données ou entraînement n'est
déduite de la réussite des tests smoke.

## 2026-11-06 — Phase 1, étape d'audit uniquement

**Autorisation.** L'utilisateur a ouvert la phase 1 et fourni localement
`data/raw/mvtec_ad/`, avec les catégories bottle, hazelnut et leather. La mission
courante est limitée à la structure, l'intégrité, les comptages, les rapports et
les tests synthétiques. Les catégories sont maintenant confirmées dans la
configuration ; aucun manifeste d'apprentissage, split, Dataset PyTorch, modèle,
entraînement ou réglage de seuil n'est autorisé par cette étape.

**Guide.** Les sections 4, 11, 15 et 16 ont été relues depuis le guide DOCX déjà
identifié. La phase 1 complète du guide couvre davantage de tâches ; le périmètre
plus étroit de la demande actuelle prévaut. Le jeu test est inspecté uniquement
pour décrire les fichiers, labels et masques, sans choix d'hyperparamètres.

### Structure et préservation des originaux

L'inspection initiale relève `bottle/bottle/{train,test,ground_truth}`, alors que
hazelnut et leather ont directement les trois dossiers attendus. Le dossier
extérieur bottle ne contient que l'emballage bottle, sans collision avec les
destinations. Chaque catégorie comprend aussi `license.txt` et `readme.txt`.

Après vérification des chemins absolus à l'intérieur du dataset et de l'absence
de conflits/liens/jonctions, les cinq éléments du bottle intérieur ont été
déplacés dans le dossier bottle extérieur avec PowerShell `Move-Item -LiteralPath`,
sans `-Force`. Aucun élément n'a été écrasé ou supprimé. Le dossier vide
`bottle/bottle` est conservé.

La preuve `reports/eda/layout_correction.json` consigne **1 393 fichiers avant et
après**, avec égalité des contenus SHA256, tailles et dates de modification après
correspondance des chemins. Ces fichiers comprennent 1 162 images, 225 masques et
6 fichiers texte. Une seconde comparaison SHA256, après l'exécution finale de
l'auditeur, confirme encore l'égalité de tous les 1 393 fichiers. L'auditeur
lui-même n'effectue aucun déplacement ni aucune écriture dans les originaux.

### Résultats mesurés

Rapport final généré le `2026-11-06T12:12:08.077661+00:00` (13:12 à Africa/Lagos).

| Catégorie | train/good | test/good | Test anormal | Masques / paires | Résolution images et masques |
| --- | ---: | ---: | ---: | ---: | --- |
| bottle | 209 | 20 | 63 | 63 / 63 | 900 × 900 |
| hazelnut | 391 | 40 | 70 | 70 / 70 | 1024 × 1024 |
| leather | 245 | 32 | 92 | 92 / 92 | 1024 × 1024 |
| Total | 845 | 92 | 225 | 225 / 225 | Selon catégorie |

Défauts observés, avec un masque apparié par image :

- bottle : broken_large 20, broken_small 22, contamination 21.
- hazelnut : crack 18, cut 17, hole 18, print 17.
- leather : color 19, cut 19, fold 17, glue 19, poke 18.

Les 1 387 images/masques sont en PNG décodable : les 1 162 images en RGB et les
225 masques en L. Aucun fichier corrompu après `verify()` puis décodage complet
`load()`, aucun masque manquant ou orphelin, aucune différence de dimensions
image/masque et aucun doublon exact d'image dans une catégorie n'a été détecté.
Les valeurs de masque ne déclenchent aucune alerte de masque vide/non binaire.

**Statut : `ok`, 0 erreur et 1 avertissement.** L'unique avertissement
`empty_nested_wrapper` concerne le dossier `bottle/bottle` vide conservé pour
respecter l'interdiction de suppression.

### Implémentation et vérifications exécutées

Fichiers créés : `src/data/audit.py`, `tests/test_audit.py`,
`reports/eda/audit.json`, `reports/eda/audit_summary.csv`,
`reports/eda/audit_by_defect.csv`, `reports/eda/layout_correction.json`.
Fichiers mis à jour : `pyproject.toml`, `configs/dataset.yaml`,
`src/data/__init__.py`, `scripts/smoke_test.py`, `tests/test_smoke.py`, `README.md`
et ce journal.

Pillow 13.0.0 a été ajouté comme dépendance directe fixée et installé dans le
`.venv` existant par le bootstrap autorisé. PyTorch reste absent. Le smoke test
accepte maintenant les phases 0 et 1 et lit seulement la configuration, sans
avoir besoin du dataset.

| Vérification réelle | Résultat |
| --- | --- |
| Bootstrap / installation éditable | Réussite ; Python 3.11.9 x64 conservé. |
| `python -m pip check` via `.venv` | `No broken requirements found.` |
| `python scripts/smoke_test.py` via `.venv` | Phase 1, `status: ok`, catégories confirmées, `data_accessed: false`. |
| `python -m pytest -q` via `.venv` | **59 passed in 2.55s** : 31 cas d'audit et 28 cas smoke. |
| Audit réel CLI | Code 0 ; résultats ci-dessus, 0 erreur / 1 avertissement. |
| Cohérence CSV/JSON | Tous les effectifs des deux CSV concordent avec le JSON. |
| Traçabilité | SHA256 du fichier `audit.py` identique à `auditor_sha256` enregistré ; empreintes des 1 387 fichiers audités vérifiées. |
| Protection Git | Les 1 393 fichiers originaux sont ignorés ; `git ls-files -- data/raw/mvtec_ad` ne retourne aucun fichier. Aucun push effectué. |

Les tests emploient seulement des images temporaires synthétiques et couvrent
comptages séparés, dimensions/formats/modes, masques manquants/orphelins/ambigus,
JPEG tronqués détectables seulement au décodage, imbrication et ambiguïté,
répertoires absents/vides/inattendus, exports et refus d'écrire dans le dataset.
Ils contrôlent aussi l'invariance des contenus et des dates de modification.
La revue a conduit à ajouter les signalements de groupes requis vides et de
dossiers supplémentaires, puis à réexécuter l'audit réel sur le code final.

Commandes reproductibles depuis la racine :

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\bootstrap.ps1
& .\.venv\Scripts\python.exe -m resilientinspect.data.audit --root data/raw/mvtec_ad --categories bottle hazelnut leather --output-dir reports/eda
& .\.venv\Scripts\python.exe -m pytest -q
```

### Limites et validation attendue

La date de téléchargement, la version précise et l'empreinte des archives
d'origine ne sont pas connues ; elles ne sont pas déduites des effectifs. Les
empreintes locales portent sur les fichiers extraits. L'audit de doublons est
exact et par catégorie ; il ne détecte pas les images similaires/réencodées.
L'égalité des tailles image/masque ne prouve pas l'alignement sémantique des
annotations. Galeries, histogrammes de luminance et inspection visuelle des
masques restent à réaliser dans une étape EDA distincte, sur validation.

**Arrêt après l'audit.** Attendre la validation explicite des rapports et de la
structure corrigée avant toute autre étape de données ou de Deep Learning.

## 2026-11-06 — Phase 1, préparation des données

**Autorisation.** L'utilisateur a validé la poursuite vers des manifestes,
une séparation déterministe 80/20 de `train/good`, un Dataset PyTorch et une
géométrie 256 × 256. Catégories inchangées : bottle, hazelnut, leather. Le test
officiel n'est ni réaffecté ni utilisé pour apprendre une normalisation ou
régler des hyperparamètres. Aucun modèle n'est construit ou entraîné.

### Protocole retenu

Pour chaque catégorie, trier les chemins relatifs puis les mélanger avec un
générateur local `random.Random(42)` réinitialisé par catégorie. Réserver les
`ceil(0.2 × N)` premières images pour `val` et conserver les autres pour `train`.
L'arrondi supérieur est explicite : le ratio exact 80/20 n'est pas possible pour
tous les effectifs entiers. Le générateur aléatoire global et l'ordre des
catégories n'affectent pas la sélection. Le split test provient exclusivement
du dossier test officiel, sans rééchantillonnage.

Colonnes CSV : `image_path,category,split,label,defect_type,mask_path,source_split,sha256,mask_sha256`.
Les chemins POSIX sont relatifs à la racine MVTec AD. Label 0 = normal, label 1 =
anormal. Les masques des images normales sont absents du CSV ; le Dataset produit
un tenseur de masque nul en mémoire. `source_split=train` permet de tracer
également la provenance officielle des lignes de validation.

Les chemins dupliqués, contenus SHA256 identiques entre splits, anomalies en
train/val et associations image/masque incohérentes sont refusés. Les fichiers
corrompus, masques non binaires et fichiers non reconnus dans les splits bloquent
la préparation ; aucun fichier n'est omis silencieusement. Un fichier de sortie
existant différent est refusé avant écriture. Une relance identique ne réécrit
pas les fichiers, préservant aussi leur date de modification.

### Géométrie et convention des tenseurs

Conserver le ratio par letterbox, sans recadrage. Facteur commun
`min(256/H,256/W)`, dimensions arrondies au plus proche (demi vers le haut),
centrage et bordures noires ; pixel de bordure supplémentaire en bas/droite si
nécessaire. PIL BILINEAR pour le RGB et NEAREST pour le masque, suivie d'une
conversion binaire `>0`. Les catégories réelles étant carrées, aucune bordure
n'est nécessaire sur les données actuelles.

Sorties : `image` float32 contiguë `[3,256,256]`, `mask` float32 binaire
`[1,256,256]`, `valid_mask`, label, catégorie, split, défaut, chemins, `has_mask`,
tailles native/redimensionnée et padding. Les pixels RGB sont divisés par 255,
constante fixée à l'avance ; aucune moyenne/variance, normalisation ImageNet ou
augmentation n'est appliquée. Le split du Dataset est obligatoire et les
empreintes des originaux sont contrôlées par défaut à la lecture.

### Effectifs générés et chargés réellement

| Catégorie | Train | Validation | Test officiel | Test normal | Test anormal |
| --- | ---: | ---: | ---: | ---: | ---: |
| bottle | 167 | 42 | 83 | 20 | 63 |
| hazelnut | 312 | 79 | 110 | 40 | 70 |
| leather | 196 | 49 | 124 | 32 | 92 |
| Total | 675 | 170 | 317 | 92 | 225 |

`data/manifests/manifest.csv` contient **1 162 lignes**. `train.csv`, `val.csv`
et `test.csv` en sont les partitions. `data/manifests/preparation.json` et
`reports/experiments/data_preparation.json` enregistrent paramètres, effectifs,
empreintes des CSV, inventaire des sources et empreintes des deux scripts.
Le SHA256 du manifeste complet est
`13f55c7cf7c87a3e3739e24920bb0d85cc96a39a00e30d277ddfaa1832b84522`.

### Vérifications réellement exécutées

PyTorch **2.15.0+cpu** a été installé depuis l'index CPU officiel, sans poids de
modèle. L'extra `data` fixe torch 2.15.0 et NumPy 2.3.5 ; Python reste 3.11.9,
Pillow 13.0.0, PyYAML 6.0.3 et pytest 9.2.0. Les versions transitives ne constituent
pas encore un environnement entièrement verrouillé.

La première suite donnait 99 réussites et un avertissement PyTorch signalant
l'absence de NumPy. La dépendance NumPy a été ajoutée explicitement, sans filtrer
l'avertissement. Après ajout du contrôle de fichier non reconnu dans un split,
la suite finale exécutée avec `-W error` donne **100 passed in 30.70s**, sans
avertissement, skip ou xfail : 31 cas audit, 34 smoke, 22 préparation, 13 Dataset.
Les contrôles historiques de phase 0 sont conservés ; seuls les invariants de
configuration désormais confirmée sont actualisés. L'absence de PyTorch reste
tolérée pour les anciennes étapes socle/audit, mais provoque une erreur explicite
pour l'étape préparation. Un test simule cette absence et vérifie le code 1.

| Vérification réelle | Résultat |
| --- | --- |
| `pip check` | `No broken requirements found.` |
| Smoke test | Phase 1, `status: ok`, PyTorch CPU requis/importé, `cuda_available: false`. |
| Génération des manifestes | Code 0 ; effectifs ci-dessus. |
| Reproductibilité synthétique | Même seed, ordre des catégories inversé et RNG global différent : mêmes lignes et mêmes octets CSV/JSON. Seed différente : validation différente, test identique. |
| Non-fuite | Disjonction de chemins et contenus entre splits ; train/val normaux issus uniquement du train officiel. |
| Reproduction réelle de seed 42 | Sélection reconstruite indépendamment depuis les fichiers présents ; égalité des lignes de validation. |
| Préservation du test | Chemins, labels, défauts, masques et empreintes des 317 images test concordent avec l'audit antérieur. |
| Chargement réel | 675 train + 170 val + 317 test parcourus ; géométrie, dtype, plages et masques binaires contrôlés. Trois batches de taille 2 vérifiés. |
| Masques après taille fixée | Aucun des 225 masques anormaux ne devient vide à 256 × 256 ; aucune taille ni interpolation ajustée sur ce résultat. |
| Originaux | 1 393 fichiers, SHA256, tailles et dates de modification identiques au relevé avant préparation. |
| Manifestes figés | Hashes CSV corrects ; réécriture à l'identique sans modification d'octets ni de mtime. |
| Git | Originaux et manifestes ignorés, aucun fichier de dataset suivi, aucun commit ni push effectué. |

Les preuves de chargement et d'intégrité sont sauvegardées dans
`reports/experiments/data_preparation_verification.json`, horodaté
`2026-11-06T12:42:30.085880+00:00` (13:42 à Africa/Lagos). Les masques test ont été
lus uniquement pour vérifier l'alignement et l'application de paramètres déjà
fixés par la demande ; aucun choix de modèle, de seuil ou d'hyperparamètre
n'en découle. Les tests du Dataset train/val vérifient qu'ils n'ouvrent aucun
fichier du test ni de ground_truth.

### Fichiers et commandes

Créés : `src/data/prepare.py`, `src/data/dataset.py`, `tests/test_prepare.py`,
`tests/test_dataset.py`, les quatre CSV et `preparation.json` sous
`data/manifests/`, `reports/experiments/data_preparation.json`,
`reports/experiments/data_preparation_verification.json`.
Modifiés : `configs/dataset.yaml`, `pyproject.toml`, `src/data/__init__.py`,
`scripts/smoke_test.py`, `tests/test_smoke.py`, `README.md`, ce journal.
Les fichiers d'audit antérieurs et les images d'origine sont conservés.

```powershell
& .\.venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.15.0+cpu"
& .\.venv\Scripts\python.exe -m pip install -e ".[dev,data]"
& .\.venv\Scripts\python.exe -m resilientinspect.data.prepare --root data/raw/mvtec_ad --output-dir data/manifests --report reports/experiments/data_preparation.json
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe scripts/smoke_test.py
& .\.venv\Scripts\python.exe -m pytest -q -W error
```

**Arrêt après la préparation.** Attendre la validation des manifestes, du ratio,
de l'arrondi et de la convention de redimensionnement. Aucun entraînement ni
nouvelle étape scientifique n'est engagé. Les limites de provenance des archives
et d'alignement sémantique des annotations, consignées après l'audit, restent valides.

## 2026-11-06 — Phase 1, EDA visuelle avant entraînement

**Périmètre autorisé.** Compléter uniquement l'EDA visuelle des trois catégories
confirmées, conformément au guide technique (EDA §4.2, séparation des usages du
test §4.3, organisation et validations §11, §15 et §16). Aucun modèle,
entraînement, réglage de seuil, nouvelle séparation ni changement de prétraitement.
Les constats sur le test restent descriptifs et ne déterminent aucun hyperparamètre.

### Mesures et figures locales

`src/data/eda.py` lit le manifeste figé et contrôle son SHA256 ainsi que celui
de chaque image et masque. Les mesures utilisent la résolution native. Le proxy
de luminance est `Y'=(0.2126R+0.7152G+0.0722B)/255` sur RGB encodé, sans
linéarisation gamma ; le contraste RMS est `std(Y', ddof=0)` par image. Aucune
statistique de normalisation n'est apprise, sur quelque split que ce soit.

Les histogrammes séparent train/good, val/good, test/good et test/anomaly :
moyenne de luminance et contraste par image, histogramme agrégé des pixels Y'.
La surface relative est le nombre de pixels non nuls du masque divisé par le
nombre de pixels de l'image native ; seules les 225 annotations anormales
contribuent aux distributions par défaut. Les normales ne créent pas de faux
masques de surface zéro.

**26 PNG générés et ouverts pour inspection** sous `reports/eda/visual/` :
3 galeries, 3 figures de distributions et 20 planches de détail couvrant toutes
les paires anormales. Les galeries montrent respectivement 9, 11 et 12 images
pour bottle, hazelnut et leather : normaux train/val/test, chaque type de défaut,
masques binaires et superpositions. Les détails affichent l'original et le
masque rouge translucide à contour jaune, sur des vues de contexte identiques.
Les recadrages et réductions d'affichage concernent uniquement les figures ;
ils ne modifient ni les fichiers natifs ni le Dataset à 256 × 256.

| Catégorie | Images mesurées | Paires inspectées | Surface min. (%) | Médiane (%) | Max. (%) |
| --- | ---: | ---: | ---: | ---: | ---: |
| bottle | 292 | 63 | 0.575679 | 5.717778 | 27.418642 |
| hazelnut | 501 | 70 | 0.232887 | 1.615810 | 27.658558 |
| leather | 369 | 92 | 0.088596 | 0.461531 | 6.859398 |
| Total | 1 162 | 225 | — | — | — |

`image_statistics.csv` conserve une ligne par image. `visual_eda_summary.json`
conserve les définitions, statistiques, histogrammes, sélections, chemins de
toutes les paires, coordonnées natives des vues et SHA256 des 26 figures.
`visual_review.json` consigne la revue réellement effectuée par l'assistant,
avec les empreintes des figures ouvertes ; elle ne constitue pas une validation
externe par un annotateur expert.

### Constats visuels et limites

- **Alignement :** les 63 paires bottle, 70 hazelnut et 92 leather ont été
  examinées sur les 20 planches de détail. Aucun mauvais appariement, décalage
  global, retournement ou rotation évident n'a été observé. Les contrôles natifs
  ne détectent ni dimensions incompatibles, ni valeurs non binaires, ni masque
  anormal vide. Cette revue sur figures ne certifie pas chaque frontière au pixel.
- **Étendue des annotations :** certains contours englobent du contexte ou des
  intervalles entre parties visibles du défaut. Exemples traçables :
  `bottle/test/contamination/008.png` (zone intérieure large),
  `hazelnut/test/print/011.png` (espaces entre traces de peinture),
  `leather/test/cut/018.png` (prolongement sombre et peu contrasté de la coupure).
  Ce sont des incertitudes sur la portée des annotations, sans preuve suffisante
  d'erreur d'association. Aucune correction de masque n'est effectuée.
- **Luminance :** les distributions train/validation se recouvrent largement.
  La moyenne par image de Y' pour leather vaut 0.286161 en train, 0.287895 en
  validation et 0.329011 en test/good ; pour hazelnut, respectivement 0.190005,
  0.189421 et 0.208367. Bottle est plus proche : 0.533745, 0.533272 et 0.538992.
  Il s'agit de différences descriptives, sans test de significativité ni cause
  d'acquisition établie. Elles ne conduisent à aucun ajustement scientifique.
- **Surfaces :** forte hétérogénéité entre types de défaut ; les défauts color
  et poke de leather peuvent être discrets à l'échelle de l'image entière.
  Le plus petit masque natif est celui de `leather/test/color/006.png`, soit
  0.088596 % de l'image. Les vues de contexte facilitent leur inspection sans
  modifier les tailles, interpolations ou paramètres du pipeline figé.

### Vérifications réellement obtenues

Matplotlib 3.10.8 est ajouté dans l'extra `eda`, avec rendu scientifique Agg sans
interface graphique. L'installation de `.[dev,data,eda]` a réussi ; `pip check`
a retourné `No broken requirements found.` Les premières planches présentaient
des légendes tronquées ; leur grille d'affichage a été corrigée, puis les
26 figures finales ont été ouvertes et les tests réexécutés.

La suite finale `python -m pytest -q -W error` donne **114 passed in 34.60s**,
sans avertissement, skip ou xfail. Les 100 tests antérieurs sont conservés ;
14 cas EDA synthétiques vérifient notamment les statistiques natives, les
superpositions, la couverture des paires, les empreintes, les erreurs de masque,
le refus d'écriture dans les sources/manifestes et l'exclusion Git des figures.

La vérification finale, horodatée `2026-11-06T13:16:52.260103+00:00`, confirme :

- **1 393 fichiers originaux inchangés**, mêmes ensembles de chemins, SHA256,
  tailles et dates de modification qu'avant l'EDA.
- **10 fichiers protégés inchangés**, SHA256 et dates de modification :
  configuration scientifique, code de préparation/Dataset, rapport de
  préparation et ensemble des fichiers de manifestes.
- SHA256 du manifeste toujours
  `13f55c7cf7c87a3e3739e24920bb0d85cc96a39a00e30d277ddfaa1832b84522`.
- Empreintes des 26 PNG vérifiées ; 225 paires uniques couvertes exactement une
  fois sur les planches ; 1 162 lignes de statistiques ; les histogrammes natifs
  conservent le nombre de pixels attendu dans chacun des groupes.
- Tout `reports/eda/visual/` est ignoré par Git, y compris les figures et preuves
  locales. Aucun fichier de ce dossier ou du dataset brut n'est suivi par Git.
  Aucun commit, push ou publication n'a été effectué.

Les empreintes et résultats du contrôle sont enregistrés localement dans
`reports/eda/visual/integrity_verification.json`. Les valeurs du tableau sont
des mesures du dataset présent, et aucune métrique de modèle n'est produite.

### Fichiers et commandes

Créés : `src/data/eda.py`, `tests/test_eda.py` et les artefacts locaux sous
`reports/eda/visual/`. Modifiés : `.gitignore`, `pyproject.toml`, `README.md` et
ce journal. Les splits, images, masques et paramètres scientifiques sont conservés.

```powershell
& .\.venv\Scripts\python.exe -m pip install -e ".[dev,data,eda]"
& .\.venv\Scripts\python.exe -m resilientinspect.data.eda --root data/raw/mvtec_ad --manifest data/manifests/manifest.csv --output-dir reports/eda/visual
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -m pytest -q -W error
```

Une relance du générateur ne vaut pas nouvelle revue sémantique : comparer les
empreintes des figures avec `visual_review.json`, puis refaire la revue si les
entrées ou le rendu ont changé. **Arrêt après cette vérification de phase 1.**
L'entraînement et toute nouvelle étape attendent la validation de l'utilisateur.

## 2026-11-07 — Phase 2, étape 1 : architecture B0 uniquement

**Autorisation.** Phase 1 validée par l'utilisateur ; implémentation de B0,
configuration et tests synthétiques seulement. Le guide technique §5.1 décrit
l'AE compact Conv–BN–ReLU / upsampling + Conv ; les sections 11, 15 et 16
déterminent les chemins, la portée bornée et les commandes PowerShell.
Le périmètre explicite de cette étape exclut les autres éléments du prompt
général de phase 2 du guide : aucun entraînement, checkpoint, MLflow, A1 ou
score/carte d'anomalie n'est ajouté.

### Architecture fixée sans consultation du test officiel

Classe : `resilientinspect.models.autoencoder.ConvAutoencoder`.
Les choix privilégient un premier modèle compact utilisable sur CPU et
ultérieurement sur GPU ; ils ne proviennent ni de scores ni d'images test.

| Bloc | Opérations | Sortie hors batch |
| --- | --- | --- |
| Entrée | RGB flottant dans [0,1] | 3 × 256 × 256 |
| Encodeur 1 | Conv 3×3, stride 2, padding 1, BN, ReLU | 16 × 128 × 128 |
| Encodeur 2 | Conv 3×3, stride 2, padding 1, BN, ReLU | 32 × 64 × 64 |
| Encodeur 3 | Conv 3×3, stride 2, padding 1, BN, ReLU | 64 × 32 × 32 |
| Encodeur 4 | Conv 3×3, stride 2, padding 1, BN, ReLU | 128 × 16 × 16 |
| Décodeur 1 | Upsample nearest ×2, Conv 3×3, padding 1, BN, ReLU | 64 × 32 × 32 |
| Décodeur 2 | Upsample nearest ×2, Conv 3×3, padding 1, BN, ReLU | 32 × 64 × 64 |
| Décodeur 3 | Upsample nearest ×2, Conv 3×3, padding 1, BN, ReLU | 16 × 128 × 128 |
| Sortie | Upsample nearest ×2, Conv 3×3, padding 1, Sigmoid | 3 × 256 × 256 |

**195 107 paramètres, tous entraînables**, comptés sur le modèle instancié :
8 Conv2d et 7 BatchNorm2d. Pas de skip connections ni poids préentraînés.
Les convolutions suivies de BN n'ont pas de biais ; la sortie RGB en possède
un. BN conserve les défauts PyTorch : eps 1e-5, momentum 0.1, affine et suivi
des statistiques activés. Initialisation PyTorch par défaut, sans règle ajoutée.
Le modèle ne redimensionne ni ne normalise les tenseurs. Il refuse les entrées
hors du contrat `[B,3,256,256]` ou de batch vide. Le constructeur accepte trois
ou quatre niveaux ; la baseline configurée en utilise quatre.

La configuration `configs/ae_baseline.yaml` fournit `model.kwargs.channels` au
constructeur ; les autres champs décrivent son contrat fixe. Perte initiale :
`torch.nn.L1Loss(reduction="mean")`, moyenne sur batch, canaux et pixels.
Le placement CPU/CUDA se fait via `model.to(device)` et les tenseurs de
l'appelant ; aucun device n'est imposé dans le forward.

### Exécutions et preuves réelles

Environnement constaté : Python **3.11.9**, PyTorch **2.15.0+cpu**, CPU,
6 threads PyTorch ; `torch.cuda.is_available()` vaut **False**. Aucune
installation de dépendance supplémentaire n'a été nécessaire.

Smoke CPU exécuté le `2026-11-07T18:08:55.495182+00:00`, sur un batch aléatoire
`[2,3,256,256]`, seed 42 :

- Les formes de chaque bloc ont été relevées sur le graphe réel et correspondent
  au tableau. Reconstruction de même dimension en modes train et eval.
- Reconstruction dans [0,1], sortie et perte finies ; rétropropagation L1 réussie.
- Tous les paramètres entraînables possèdent des gradients finis ; gradients
  non nuls dans la première convolution encodeur et la dernière convolution
  décodeur. Aucun NaN/Inf observé dans ces contrôles.
- Aucun optimiseur ni pas de mise à jour des poids ; aucun checkpoint.
  Le forward en mode train met uniquement à jour les buffers BN de cette
  instance de diagnostic, ensuite abandonnée.
- La valeur L1 mesurée sur du bruit et des poids aléatoires est sauvegardée comme
  diagnostic numérique uniquement ; elle n'est pas une métrique de qualité B0.

| Commande réellement exécutée | Résultat |
| --- | --- |
| `python -m pytest tests/test_models.py -q -W error` | **22 passed, 1 skipped in 6.79s** |
| `python -m pytest -q -W error` | **136 passed, 1 skipped in 34.40s** |

Le seul skip est le test explicite `test_cuda_synthetic_forward_and_backward` :
CUDA est indisponible localement. La compatibilité d'exécution GPU reste donc
**à vérifier sur Kaggle/Tesla T4**, sans prétendre qu'elle a déjà été validée.
Les tests CPU couvrent batchs 1/2, modes train/eval, images constantes noire et
blanche, gradients, entrées invalides, configuration et rechargement du state_dict
en mémoire (y compris les buffers BN). Les 114 tests antérieurs passent ; aucune
erreur n'a été masquée ni aucun ancien test modifié.

Les preuves d'architecture, valeurs diagnostiques, environnement, SHA256 du
modèle/configuration/tests et sorties Pytest sont conservées dans
`reports/experiments/b0_architecture_smoke.json`.

### Données et protocole conservés

Les nouveaux tests et le smoke utilisent uniquement des tenseurs synthétiques ;
aucune image ou masque MVTec AD n'a été ouvert pour développer ce modèle.
La vérification finale confirme les SHA256 et dates de modification inchangés de
**12 fichiers protégés** (configuration dataset, modules de données, manifestes).
L'inventaire des **1 393 fichiers originaux**, leurs tailles et dates de
modification sont identiques avant/après. Leurs contenus ne sont pas relus pour
recalculer les SHA256 durant cette étape : cette limite du contrôle d'intégrité
est explicite. Aucun contenu du dataset ou des manifestes n'est suivi par Git.
Les catégories, splits, seed et prétraitements validés restent inchangés.

Créés : `src/models/autoencoder.py`, `configs/ae_baseline.yaml`,
`tests/test_models.py`, `reports/experiments/b0_architecture_smoke.json`.
Modifiés : `src/models/__init__.py` (description), `README.md`, ce journal.
Le script ponctuel du smoke et le relevé avant modification restent dans le
cache local ignoré ; le README fournit un smoke CPU autonome reproductible.

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_models.py -q -W error
& .\.venv\Scripts\python.exe -m pytest -q -W error
```

**Arrêt après l'architecture B0 et ses vérifications.** La prochaine étape
d'entraînement nécessite la validation de l'utilisateur. Aucun résultat de
modèle sur MVTec AD, A1, T0/T1/T2 ou exécution CUDA n'est revendiqué.

## 2026-11-07 — Phase 2, étape 2 : pipeline B0 et smoke CPU

**Autorisation.** Architecture B0 validée par l'utilisateur ; préparer le
pipeline reproductible CPU/Kaggle T4 et exécuter uniquement un court entraînement
CPU de vérification, en commençant par bottle. Références : guide §5.1, §6,
§11, §15 et §16. Aucun run complet CPU, A1, T0/T1/T2, évaluation test, export
ou service de déploiement n'est ajouté.

### Protocole initial, sans optimalité démontrée

| Paramètre | Choix initial |
| --- | --- |
| Catégorie par défaut | bottle ; un modèle/optimiseur neuf par appel |
| Taille et prétraitement | 256 × 256, letterbox bilinear/nearest, pixels /255 inchangés |
| Batch size / maximum d'époques | 16 / 20 |
| Optimiseur | Adam, lr 0.001, betas 0.9/0.999, eps 1e-8, weight decay 0 |
| Perte | L1 moyenne sur batch, canaux et pixels |
| Sélection | Plus petite L1 val, strictement ; conserver le premier en cas d'égalité |
| Early stopping | Patience 5, min_delta 0 ; compteur séparé du minimum strict du checkpoint |
| Seed | 42, Python / NumPy / PyTorch / DataLoader et workers |
| Précision | AMP désactivée ; activer mixed_precision est refusé à cette étape |
| Chargement | num_workers 0, drop_last false ; train mélangé, val ordonné |
| Smoke seulement | Une époque, batch size 2, au plus deux mini-batches par split, num_workers 0 |

Ces choix sont enregistrés dans `configs/train_ae_b0.yaml` pour permettre une
future comparaison contrôlée B0/A1. La configuration du modèle et le Dataset
existants sont réutilisés sans modification. Les champs de configuration
inconnus sont refusés pour éviter des paramètres enregistrés mais ignorés.

Le pipeline ne construit que `MVTecDataset(split="train")` et
`MVTecDataset(split="val")`, pour une seule catégorie. Les deux groupes exigent
label normal, provenance officielle train et absence de masque. Le manifeste
figé est contrôlé par SHA256 à partir de `preparation.json`. Les métadonnées
du manifeste complet sont lues pour les contrôles structurels ; aucune image
ou annotation test n'est ouverte. Les mises à jour Adam utilisent train ; val
utilise eval sans gradient ni mise à jour des buffers BatchNorm. La perte
d'époque est pondérée par le nombre d'images, y compris le dernier batch court.

Les algorithmes déterministes sont requis, cuDNN benchmark désactivé,
`CUBLAS_WORKSPACE_CONFIG=:4096:8` fixé avant exécution GPU. Chaque appel
réinitialise modèle et optimiseur, crée un nouveau run et un nouveau dossier.
Il n'existe pas de reprise implicite de checkpoint. L'identité entre versions
PyTorch ou entre CPU et CUDA n'est pas garantie ; la reproductibilité testée
concerne deux runs synthétiques dans le même environnement CPU.

### Suivi MLflow et dépendances

MLflow suit l'expérience `resilientinspect-ae`, avec tags variant, catégorie,
seed, scope, version dataset (SHA256 du manifeste), Git SHA et split de sélection.
Paramètres effectifs, séries train/val par époque, meilleur checkpoint, CSV,
figure des pertes, environnement, chemins des images réellement utilisées et
sources sont sauvegardés localement et enregistrés comme artefacts. Le statut
d'un run interrompu en erreur est `FAILED`. Un smoke porte explicitement
`scope=smoke` ; son checkpoint reste séparé des runs complets.

Backend SQLite local : `artifacts/training/mlflow.db`, artefacts sous
`artifacts/training/mlartifacts/`. Aucun serveur distant n'est configuré.
L'extra `train` contient MLflow Skinny 3.16.1, SQLAlchemy 2.0.57, Alembic 1.20.1
et Matplotlib 3.10.8, sans dépendance PyTorch. Aucun code du pipeline ne lance pip.
Les sources sont copiées avec leurs empreintes pour conserver l'état exact même
si Git indique des modifications non commitées.

L'installation initiale avec SQLAlchemy 2.1.8 a déclenché un
`SADeprecationWarning` sur la stratégie `noload` utilisée par MLflow. La première
suite ciblée a donc donné 14 réussites et 5 erreurs avec `-W error`. SQLAlchemy
a été fixé à **2.0.57** ; aucun filtre d'avertissement n'a été ajouté. Une suite
ciblée intermédiaire a ensuite donné 19 réussites en 50.07 s. Après ajout du
contrôle des champs inconnus et des copies de sources, la suite finale contient
20 nouveaux tests de pipeline, tous réussis.

Les rapports d'installation pip confirment qu'aucun paquet torch n'a été
installé ou remplacé. PyTorch reste **2.15.0+cpu**, NumPy **2.3.5**, Pillow
**13.0.0**, PyYAML **6.0.3**. `pip check` donne `No broken requirements found.`
L'installation éditable a été rafraîchie avec `--no-deps --no-build-isolation`.

### Smoke officiel réellement exécuté

Commande PowerShell :

```powershell
& .\.venv\Scripts\python.exe -W error -m resilientinspect.training.train_ae --config configs/train_ae_b0.yaml --root data/raw/mvtec_ad --manifest data/manifests/manifest.csv --category bottle --device cpu --output-dir artifacts/training --smoke
```

Run MLflow **`b453d9b1af9d4186abcffa41afc10a87`**, statut **FINISHED**.
Dossier local ignoré :
`artifacts/training/bottle/smoke_b453d9b1af9d4186abcffa41afc10a87/`.

| Mesure effective | Résultat |
| --- | --- |
| Époques terminées / meilleur checkpoint | 1 / époque 1 |
| Images disponibles bottle train / val | 167 / 42 |
| Batches réellement parcourus train / val | 2 / 2 |
| Images réellement utilisées train / val | 4 / 4 |
| Pas Adam | 2, vérifiés dans l'état de l'optimiseur sauvegardé |
| L1 moyenne train, partielle | 0.2950199544429779 |
| L1 moyenne val, partielle | 0.3324028551578522 |
| Image/masque test utilisé | Aucun |

Ces pertes sont des diagnostics d'exécution sur un budget minuscule, sans
interprétation de qualité de détection. Aucune AUROC, AP, F1 ou métrique pixel
n'est calculée. Les poids diffèrent de l'initialisation ; les tenseurs du
checkpoint sont finis, les compteurs BN indiquent seulement les deux batches
train. Le checkpoint a été rechargé sur CPU, puis téléchargé depuis le stockage
d'artefacts MLflow local : même SHA256. Les séries de métriques MLflow sont
identiques aux valeurs du CSV et du résumé. La figure des pertes a été ouverte
et contrôlée ; une seule époque produit deux points, pas une courbe de convergence.

### Tests et intégrité vérifiés

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -W error --tb=short
```

Résultat final : **156 passed, 1 skipped in 100.09s**. Le seul skip est le test
CUDA existant de `test_models.py`, faute de GPU local. Aucun ancien test n'est
modifié. Les nouveaux tests couvrent : entraînement synthétique avec MLflow
réel, absence de lecture test/masques/autres catégories, absence de mise à jour
des poids et buffers en validation, reproductibilité exacte des historiques et
tenseurs de deux checkpoints CPU, moyenne pondérée du dernier batch, early
stopping, sélection sur val plutôt que train, échec correctement propagé,
configuration, manifeste modifié, protection des répertoires et CLI.

Le test de sélection multi-époques utilise des pertes simulées uniquement en
répertoire temporaire ; il ne représente pas un entraînement officiel ni une
mesure expérimentale. Le seul entraînement officiel exécuté ici est le smoke
bottle décrit ci-dessus.

Vérification finale enregistrée dans
`reports/experiments/b0_training_verification.json` :

- **14 fichiers protégés inchangés**, mêmes SHA256 et dates : manifestes,
  configuration dataset, modules de données, architecture B0 et sa configuration.
- **1 393 fichiers originaux**, même inventaire, tailles et dates de modification.
  Le contrôle ne relit pas les contenus test pour recalculer leurs empreintes.
- Chemins train et val réellement utilisés disjoints, tous sous
  `bottle/train/good/` ; aucun masque ou autre catégorie dans ces lectures.
- 10 artefacts de premier niveau et un dossier de 9 copies de sources présents
  dans MLflow ; métriques, checkpoint et paramètres vérifiés par le client.
- Toutes les sorties de l'entraînement sont ignorées par Git. Aucun dataset,
  manifeste ou checkpoint n'est suivi ; aucun commit, push ou publication.

### Fichiers et préparation Kaggle

Créés : `src/training/train_ae.py`, `configs/train_ae_b0.yaml`,
`tests/test_training.py`, `reports/experiments/b0_training_verification.json`.
Modifiés : `src/training/__init__.py`, `pyproject.toml`, `.gitignore`,
`README.md`, ce journal. Les checkpoints, métriques détaillées, figures et
copies d'artefacts restent sous `artifacts/training/`, hors Git.

Le README fournit les commandes CPU réelles et les cellules Kaggle : installation
de `.[train]` exclusivement, contrôle que la version torch installée ne change
pas, chemins explicites vers le dataset et les manifestes figés, `--device cuda`
sans repli silencieux, sorties dans `/kaggle/working`. Ne pas installer `.[data]`
ni une roue CPU sur le notebook CUDA. Le contrat de paquetage reste Python 3.11 ;
vérifier l'interpréteur Kaggle avant installation. Aucun notebook, GPU T4 ou
run complet n'a été exécuté/validé depuis cet environnement CPU.

**Arrêt après le pipeline et sa vérification courte.** Attendre la validation
avant tout entraînement complet et avant A1/T0/T1/T2.

## 2026-11-08 — Correction de compatibilité Python / Kaggle

**Périmètre.** Adapter le contrat de paquetage et les contrôles de runtime à
Python 3.11–3.13, sans modifier B0, ses configurations, l'entraînement, les
données ou le protocole scientifique. L'utilisateur communique Python 3.13.16,
PyTorch 2.11.0+cu130 et Tesla T4 sur Kaggle. Ce runtime distant n'a pas été
inspecté ou exécuté depuis l'environnement local ; il reste à vérifier.

### Modifications

- `pyproject.toml` déclare désormais `requires-python = ">=3.11,<3.14"`.
  Toutes les versions de dépendances restent identiques. L'extra `data` impose
  toujours torch 2.15.0 pour la reproduction locale et ne doit pas être installé
  sur Kaggle ; les extras `train,eda,dev` ne demandent pas de runtime Torch/CUDA.
- Le smoke Python accepte les trois versions mineures en x64, conserve le
  rejet de Python 3.10, 3.14 et des interpréteurs 32 bits et annonce les versions
  acceptées dans son JSON. L'absence de PyTorch requis reste une erreur.
- Le bootstrap PowerShell applique le même contrat, conserve le `.venv` valide
  et recherche 3.11, puis 3.12 et 3.13 en cas de création nécessaire.
- Aucun test antérieur n'est supprimé ou désactivé. Seize cas sont ajoutés :
  bornes Python/x64, cohérence des métadonnées installées, arbre de dépendances
  Kaggle sans Torch/CUDA et probe PowerShell simulant plusieurs versions et un
  code de sortie en erreur, sans créer de venv.
- La cellule README Kaggle utilise les extras `train,eda,dev`, contraint les
  versions déjà installées de torch/torchvision/torchaudio/triton et des
  distributions CUDA/NVIDIA, puis vérifie qu'elles sont inchangées. Elle prévoit
  `pip check`, Pytest et le smoke GPU dans le notebook. Elle n'est pas exécutée
  depuis cette machine et ne demande jamais une roue CPU ou l'extra `data`.

### Compatibilité des distributions : preuves de métadonnées

Les versions exactes ont été interrogées via l'API publique PyPI. Les dix
dépendances directes épinglées, backend de construction inclus, déclarent des
contraintes `Requires-Python` autorisant 3.11, 3.12 et 3.13.16. Des roues Linux
CPython 3.13, abi3 ou universelles sont présentes pour chacune.

| Distribution | Version | Requires-Python déclaré |
| --- | --- | --- |
| setuptools (backend requis) | 80.9.0 | >=3.9 |
| PyYAML | 6.0.3 | >=3.8 |
| Pillow | 13.0.0 | >=3.11 |
| pytest | 9.2.0 | >=3.10 |
| torch local | 2.15.0 | >=3.11 |
| NumPy | 2.3.5 | >=3.11 |
| Matplotlib | 3.10.8 | >=3.10 |
| MLflow Skinny | 3.16.1 | >=3.10 |
| SQLAlchemy | 2.0.57 | >=3.7 |
| Alembic | 1.20.1 | >=3.10 |
| torch Kaggle communiqué | 2.11.0 | >=3.10 |

Sources primaires : [MLflow Skinny 3.16.1](https://pypi.org/project/mlflow-skinny/3.16.1/),
[PyTorch 2.11.0](https://pypi.org/project/torch/2.11.0/), autres URL versionnées
PyPI conservées dans `reports/experiments/python_compatibility.json`.
L'[index officiel cu130](https://download.pytorch.org/whl/cu130/torch/) contient
une roue `torch-2.11.0+cu130-cp313-cp313` manylinux x86_64 ; aucune roue torch
n'a été téléchargée ou installée. La présence de ce fichier et les déclarations
Python ne valident pas les kernels CUDA sur la T4.

Une simulation pip avec `--dry-run --ignore-installed --python-version 3.13.16`,
tags de roues manylinux x86_64, `--implementation cp --abi cp313` et
`--only-binary=:all:` a réussi pour neuf dépendances directes épinglées hors
torch, dont NumPy. **62 paquets proposés, zéro paquet Torch/CUDA**, sans
installation. Le rapport pip et les métadonnées brutes restent dans le cache
local ; les versions choisies et empreintes sont reprises dans le rapport textuel.

**Limite explicite :** pip est exécuté par Windows/Python 3.11.9 ; les options de
cible contrôlent les tags des roues et `Requires-Python`, mais des marqueurs de
dépendances peuvent rester évalués selon l'hôte. Le rapport enregistre ainsi
Windows/3.11.9 et inclut colorama. Ce contrôle est une simulation de résolution,
pas un test natif Linux/Python 3.13, ni une validation complète de l'environnement
Kaggle préinstallé. La résolution et les tests doivent être répétés dans Kaggle.

### Résultats réellement obtenus localement

| Vérification exécutée | Résultat |
| --- | --- |
| Installation éditable `pip install --no-deps --no-build-isolation -e .` | Réussie ; contrat des métadonnées mis à jour, aucune dépendance réinstallée |
| Bootstrap `-SkipInstall` | Code 0 ; `.venv` 3.11 x64 conservé, aucune installation |
| `python scripts/smoke_test.py` | Code 0, status ok ; Python 3.11.9, PyTorch 2.15.0+cpu, CUDA false |
| `python -m pytest tests/test_compatibility.py tests/test_smoke.py -q -W error --tb=short` | **50 passed in 20.76s** |
| `python -m pytest -q -W error --tb=short` | **172 passed, 1 skipped in 93.57s** |
| `pip check` | `No broken requirements found.` |

Le seul skip local reste le test CUDA existant de `test_models.py`. Les nouveaux
tests sur les valeurs 3.12/3.13 sont des contrôles de politique d'acceptation et
de métadonnées ; ils ne prétendent pas exécuter ces interpréteurs. Le test du
probe PowerShell est spécifique Windows et sera ignoré sur Linux.

Les premiers contrôles ont révélé un ancien répertoire généré et ignoré
`resilientinspect_ai.egg-info` à la racine, dont le champ `<3.12` masquait les
métadonnées `<3.14` correctement installées dans le `.venv`. Il a été déplacé
sans suppression ni écrasement dans `.pytest_cache/python_compat_legacy_metadata`.
Les tests ont ensuite validé l'accord entre `pyproject.toml` et la distribution
installée. Le test PowerShell temporaire utilise la même politique de processus
RemoteSigned que le bootstrap, sans changement de politique système. Aucun
filtre d'avertissement ni contournement des échecs n'a été ajouté.

L'environnement réellement exécuté reste Python 3.11.9 / PyTorch 2.15.0+cpu.
Le rafraîchissement de métadonnées sans isolation utilise le setuptools local
78.1.0 ; la vérification de setuptools 80.9.0 concerne sa version requise dans
le build-system et ses métadonnées officielles. Aucun PyTorch CUDA n'est remplacé
et aucun environnement Kaggle n'est modifié depuis cette session.

### Conservation du protocole et fichiers

Le relevé avant/après confirme **16 fichiers scientifiques protégés inchangés**,
mêmes SHA256 et dates : les trois YAML, modules de données, modèle B0,
pipeline d'entraînement et manifestes. Les **1 393 fichiers originaux** ont le
même inventaire, les mêmes tailles et dates ; aucun contenu d'image ou masque
officiel n'est relu pour cet audit de compatibilité. Aucun nouvel entraînement
MVTec AD ni entraînement complet n'est lancé ; Pytest conserve ses vérifications
sur données synthétiques temporaires.

Modifiés : `pyproject.toml`, `scripts/smoke_test.py`, `scripts/bootstrap.ps1`,
`tests/test_smoke.py` (ajouts uniquement), `README.md`, ce journal.
Créés : `tests/test_compatibility.py`,
`reports/experiments/python_compatibility.json`.

**Arrêt après la correction de compatibilité.** Python 3.13.16, le runtime
PyTorch 2.11.0+cu130, MLflow/SQLite et le smoke B0 sur Tesla T4 restent à vérifier
réellement dans Kaggle avant la validation d'un entraînement complet.
## 8 novembre 2026 — module d'évaluation B0, implémentation pour revue

**Statut : arrêt avant calibration réelle et avant évaluation du test officiel.**
Demande bornée au module d'évaluation des trois B0 déjà entraînés sur Kaggle.
Le guide a été relu depuis `resilientinspect-ai/guide_technique.docx.docx`
(le chemin `docs/guide_technique.docx` n'existe pas dans cet état du dépôt).
Sections 4–6, 11, 15 et 16 prises en compte ; aucune phase A1/transfert/export/API
n'est implémentée. Aucune publication Git ou GitHub.

### Choix scientifiques proposés avant accès au test

Le protocole détaillé est dans
[`b0_evaluation_protocol.md`](b0_evaluation_protocol.md), avec paramètres dans
`configs/evaluate_ae_b0.yaml` :

- carte L1 : moyenne des erreurs absolues RGB, sans lissage ni normalisation par image ;
- score image : moyenne des `ceil(0,01 × N)` plus grandes erreurs sur N pixels valides ;
- seuil image : quantile 95 % des scores des normales val de chaque catégorie ;
- seuil pixel : quantile 99,5 % des erreurs de tous les pixels valides de val normale ;
- quantiles `higher`, décisions strictement `>`, padding toujours exclu des calculs ;
- AUROC/AP sur scores continus, Dice/IoU micro incluant les faux positifs normaux,
  macro intercatégories et conventions explicites pour les valeurs indéfinies ;
- confusion et F1 image au seul seuil val, aucun maximum F1/Dice/IoU recherché sur test.

Le choix sans lissage constitue la proposition de baseline brute au regard du
§5.1 du guide, qui évoque une carte lissée, et du §5.4 qui prévoit cette ablation.
Il attend validation avec le score top-1 % et les quantiles avant toute inférence
officielle. Les réglages d'entraînement B0 ne changent pas. Val a déjà servi à
sélectionner le checkpoint : le réemploi pour calibrer le seuil est documenté,
sans annoncer un taux de faux positifs futur garanti ou une validation indépendante.

### Checkpoints réels inspectés, sans inférence

Chargement CPU `weights_only=True`, strict, en mode eval et sans gradients.
SHA256 des poids et manifeste contrôlés. Manifeste global inchangé :
`13f55c7cf7c87a3e3739e24920bb0d85cc96a39a00e30d277ddfaa1832b84522`.

| Catégorie | Run complet retenu | Meilleure époque enregistrée |
| --- | --- | --- |
| bottle | `7b8b71d28bc44868840ca50f4b16f4a1` | 19 |
| hazelnut | `7ad19992bae44fcb9a04b5e7e15eccaf` | 18 |
| leather | `15ee92b51d3e4ff99632422619e64c00` | 14 |

Le run smoke bottle et quatre copies MLflow sont exclus, soit cinq fichiers
`best.pt` exclus pour trois retenus. Plusieurs runs complets distincts pour la
même catégorie bloquent la sélection ; les copies identiques sont dédupliquées.
L'inventaire local est dans
`reports/evaluation/b0/f515662ab4ef/checkpoint_inventory.json` et sa version
textuelle à chemins relatifs est reprise dans le rapport de vérification.
Ces contrôles ne mesurent aucune performance de détection.

### Vérifications réellement exécutées

| Commande / contrôle | Résultat |
| --- | --- |
| Installation de `scikit-learn==1.8.0` avec rapport pip local | Réussie ; ajouts scikit-learn, SciPy 1.17.1, joblib 1.6.0, threadpoolctl 3.8.0 ; Torch et NumPy non remplacés |
| Installation éditable `pip install --no-deps --no-build-isolation -e .` | Code 0 ; avertissement informatif du backend sur l'installation éditable, aucune dépendance réinstallée |
| Premier `pytest tests/test_evaluation.py -q -W error --tb=short` | 47 passed in 31.43s, avant deux contrôles complémentaires |
| `pytest -q -W error --tb=short` final | **221 passed, 1 skipped in 72.11s** ; 49 tests d'évaluation inclus |
| `pip check` | `No broken requirements found.` |
| `python -W error -m resilientinspect.evaluation.evaluate_ae --stage inspect --device cpu` | Code 0, trois poids complets chargés, aucun Dataset ni inférence |
| `git diff --check` | Code 0 |

Le seul skip est le contrôle CUDA existant, faute de GPU local. Environnement
réel : Python 3.11.9, PyTorch 2.15.0+cpu, NumPy 2.3.5. L'extra `eval` est ajouté
sans exigence Torch ; le test existant de dépendances Kaggle est étendu à cet
extra, sans supprimer d'assertion. Les métadonnées installées sont compatibles
avec Python 3.13 selon ce contrôle, ce qui ne valide pas l'exécution Kaggle.

Les tests d'évaluation utilisent des images et checkpoints aléatoires temporaires
sans entraînement. Ils vérifient les calculs sur des cas connus, les ex æquo,
les masques vides, la non-fuite, le blocage du test avant accord ou sur calibration
périmée/modifiée, l'absence de mutation des poids/BatchNorm, l'exclusion des smoke
et copies MLflow, ainsi que deux exécutions CPU identiques au niveau seuils,
métriques et octets CSV/JSON/PNG. Le CLI complet calibration/évaluation est aussi
exercé sur les trois catégories **synthétiques**, avec rapports et figures.
La suite historique conserve ses mini-batches d'entraînement synthétiques de
régression ; aucun entraînement MVTec AD ni entraînement complet n'est lancé.

Une figure synthétique bottle/crack a été inspectée : quatre panneaux lisibles,
géométrie entrée/masque alignée, échelle heatmap fixe [0,1]. La reconstruction
provient d'un modèle initialisé aléatoirement et ne permet aucune conclusion
sur les B0 entraînés. Aucun seuil ou résultat test réel n'est produit.

### Conservation et sorties

Comparaison avant/après : **16 fichiers scientifiques** (configurations B0,
sources données/modèle/entraînement, manifestes) inchangés en SHA256 et date ;
**157 fichiers des runs B0** inchangés en inventaire, SHA256 et date, base MLflow
incluse. Les **1 393 fichiers originaux** gardent inventaire, taille et date ;
leur contenu image/masque n'est pas relu durant cette étape.

Créés : `src/evaluation/evaluate_ae.py`, `configs/evaluate_ae_b0.yaml`,
`tests/test_evaluation.py`, `reports/experiments/b0_evaluation_protocol.md`,
`reports/experiments/b0_evaluation_verification.json`.
Modifiés : `src/evaluation/__init__.py`, `pyproject.toml`, `.gitignore`,
`tests/test_compatibility.py`, `README.md`, ce journal.
Tous les futurs rapports/figures `reports/evaluation/` restent locaux et ignorés
par Git. Un résultat différent existant ne peut pas être écrasé.

L'évaluation officielle exige le SHA256 exact du protocole validé, les seuils
val normaux et des empreintes compatibles. Le fichier compagnon de calibration
contrôle son intégrité. **Aucun stage calibrate/evaluate n'est exécuté sur les
données réelles. Arrêt pour revue et validation du protocole.**

## 8 novembre 2026 — A1 résiduel, implémentation et smoke CPU seulement

**Périmètre autorisé :** candidat A1 selon guide §5.2, intégration au pipeline
existant, tests et petit smoke CPU. Aucun entraînement complet ni test A1
officiel. B0 reste une référence figée. Aucun résultat, score ou exemple test B0
n'est consulté pour choisir les composants A1 ; seul leur inventaire/SHA256 est
calculé pour vérifier leur conservation.

### Choix fixés avant entraînement complet et avant test A1

Le document [`a1_protocol.md`](a1_protocol.md) et les YAML
`configs/ae_improved.yaml`, `configs/train_ae_a1.yaml` fixent :

- canaux 32/64/128/256, quatre niveaux Conv–BN–ReLU + blocs résiduels à deux
  convolutions, latent 256×16×16 ; décodeur nearest/Conv résiduel, Sigmoid RGB ;
- deux skips seulement à 32×32 et 64×64, projection 1×1 + tanh ×0,1, contribution
  bornée à ±0,1 ; aucun skip à 128×128 ou chemin RGB direct ;
- **2 754 371 paramètres**, capacité supérieure à B0 (195 107), sans preuve de
  qualité supérieure ; le risque de reconstruction des défauts subsiste ;
- perte **0,8 L1 + 0,2 DSSIM**, DSSIM=(1−SSIM)/2 ; fenêtre gaussienne 11×11,
  sigma=1,5, RGB par canal, L=1, K1=0,01/K2=0,03, moments population, convolution
  valid, calcul FP32 ; pas de MS-SSIM ou paquet supplémentaire ;
- augmentation photométrique train/good uniquement : probabilité 0,5, luminosité
  et contraste uniformes entre 0,9 et 1,1, clipping [0,1], padding conservé nul,
  aucune transformation géométrique ; entrée augmentée aussi utilisée comme cible ;
- options résidus, skips, perte et augmentation séparées pour de futures ablations
  explicites et identifiées avant test.

La stabilité SSIM locale a été vérifiée **avant le smoke réel** : oracle NumPy
2D indépendant en FP64 (tolérance 1e−12), cas constant analytique, identité,
images presque constantes, gradients finis et gradcheck PyTorch. Cela ne valide
pas un gain de détection ou l'entraînement complet CUDA. Les définitions et
sources primaires SSIM sont dans le protocole.

Mêmes splits/manifestes, résolution 256×256, seed 42, batch 16, maximum 20
époques, patience 5, min_delta 0, Adam LR=0,001, mêmes betas/eps/weight_decay,
AMP désactivée. Val sans augmentation sélectionne le meilleur checkpoint par
**perte composite**, avec enregistrement séparé de L1 et DSSIM. Une perte
composite A1 n'est pas directement comparable à la L1 B0. Aucun masque test ni
normalisation sur test. Val demeure réutilisée pour la sélection puis la future
calibration, avec les limites déjà documentées.

Le futur protocole de score/seuillage reste celui de B0 : carte L1 brute RGB,
top-1 %, quantiles val normaux 95 % image / 99,5 % pixel, higher, décision >,
padding exclu. Les **valeurs numériques des seuils** devront être recalibrées
sur val normale pour A1. L'évaluation A1 n'est pas implémentée ou exécutée ici.

### Intégration et protections

La boucle commune `src/training/train_ae.py` gère les deux variantes sans copier
la logique Adam, validation, early stopping, sélection ou MLflow. B0 conserve
sa classe et sa perte. Chaque catégorie reçoit un nouveau modèle/optimiseur.
Les checkpoints A1 embarquent l'architecture et les options scientifiques,
configuration effective, état optimiseur, époque, seed et manifeste. Le helper
`load_a1_checkpoint` recharge cette architecture intégrée et vérifie poids et
échelles de skips, sans dépendre d'un YAML courant potentiellement modifié.
Provenance et sources des nouveaux modules sont sauvegardées dans chaque run.

Sortie par défaut A1 : `artifacts/a1_runs/`, avec tag MLflow variant=A1 et
expérience commune `resilientinspect-ae`. Les sorties dans les répertoires B0
figés sont refusées. Un A1 complet sur CPU est bloqué avant lecture d'images ;
le smoke est limité à une époque, batch 2 et au plus deux mini-batches par split.
La CLI accepte séparément bottle, hazelnut, leather.

### Commandes exécutées et résultats réels

| Vérification | Résultat |
| --- | --- |
| `python -m pytest tests/test_training.py -q -W error --tb=short` | **20 passed in 29.59s** : régression du pipeline B0 |
| `python -m pytest tests/test_improved.py -q -W error --tb=short` | **49 passed, 1 skipped in 33.81s** |
| `python -W error .pytest_cache/a1_cpu_smoke.py` | Code 0 ; lanceur local gardé appelant le pipeline A1 réel bottle/cpu/smoke ; seulement huit images bottle/train/good ouvertes |
| `python -m pytest -q -W error --tb=short` final | **270 passed, 2 skipped in 80.74s** |
| `python -m pip check` | `No broken requirements found.` |
| `git diff --check` | Code 0 |

Les deux skips sont CUDA : B0 existant et A1 forward/backward avec SSIM. Aucun
filtre d'avertissements ajouté. Les tests A1 vérifient dimensions, plage Sigmoid,
gradients encodeur/décodeur/skips, ablations indépendantes, référence SSIM,
reproductibilité de deux smokes synthétiques, checkpoints, suivi MLflow,
absence de mutation en val et absence d'accès aux images/masques test. Les trois
catégories de la CLI sont contrôlées sans lancer de run complet.

Smoke **réel bottle CPU**, run MLflow `a17655f1dae04138a0ee028fc96766f9`, statut
`FINISHED`, scope smoke, meilleur checkpoint époque 1 :

| Mesure partielle | Train | Val |
| --- | --- | --- |
| Images traitées | 4 | 4 |
| Mini-batches | 2 | 2 |
| Perte composite | 0.32631225883960724 | 0.32048381865024567 |
| L1 brute | 0.30197781324386597 | 0.3340425193309784 |
| DSSIM | 0.42365002632141113 | 0.2662489414215088 |

Deux pas Adam sont vérifiés dans le checkpoint, poids modifiés par rapport à
l'initialisation seed 42, compteurs BN à deux batches train. Rechargement du
checkpoint et forward synthétique finis. Le garde `Image.open` du lanceur
refuse tout chemin hors bottle/train/good, y compris test et ground_truth.
Ces pertes de contrôle **ne sont ni des performances de détection, ni une
comparaison B0/A1, ni un entraînement complet**.

### Conservation, compatibilité et fichiers

Comparaison avant/après : **157 fichiers des runs B0**, **34 fichiers de résultats
B0** et **6 fichiers de manifestes** inchangés en inventaire, SHA256 et date.
Les huit fichiers scientifiques B0/dataset protégés restent identiques en SHA256
et date. Les **1 393 fichiers originaux** gardent inventaire, taille et date ;
aucun contenu d'image/masque test officiel n'est lu.

Le premier export des preuves a rencontré une incohérence de séparateurs Windows
dans son dictionnaire de chemins ; le script d'export a été corrigé et la
comparaison relancée. Aucun échec du modèle ou de la suite Pytest associé.
Les preuves, empreintes figées et chemins des huit images du smoke sont dans
`a1_implementation_verification.json`.

Créés : `src/models/autoencoder_improved.py`, `src/training/losses.py`,
`src/training/a1_config.py`, `src/data/augment.py`, `configs/ae_improved.yaml`,
`configs/train_ae_a1.yaml`, `tests/test_improved.py`,
`reports/experiments/a1_protocol.md`,
`reports/experiments/a1_implementation_verification.json`.
Modifiés : `src/training/train_ae.py`, `src/training/__init__.py`, `README.md`,
ce journal. Les lanceurs/probes temporaires et artefacts restent ignorés par Git.

Aucune dépendance installée ou remplacée. Python >=3.11,<3.14 reste déclaré ;
runtime réellement exécuté Python 3.11.9 / PyTorch 2.15.0+cpu. Les opérations A1
utilisent les API PyTorch existantes. La procédure Kaggle conserve Torch/CUDA
préinstallés, sans extra `data`. **Python 3.13/PyTorch 2.11.0+cu130/Tesla T4,
stabilité CUDA et mémoire batch16 restent à vérifier réellement.**

**Arrêt pour validation après implémentation, tests et smoke CPU ; aucun
entraînement complet A1 ou test officiel A1 lancé.**
