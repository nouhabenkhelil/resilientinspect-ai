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
