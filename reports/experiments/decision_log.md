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
