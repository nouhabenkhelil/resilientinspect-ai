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
