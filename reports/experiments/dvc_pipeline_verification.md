# Vérification du pipeline DVC — 27 novembre 2026

Pipeline de développement **réellement exécuté** : prétraitement, entraînement
CPU et évaluation indépendante. Travail réalisé dans le worktree dédié
`C:\Users\nouhe\resilientinspect-dvc`, branche `feature/mlops-dvc-pipeline`,
HEAD conservé `70c61534d888c4ab1effd2eae5e802229ca3a04d`.
Le worktree principal, sa branche et ses modifications non commitées sont préservés.
Aucun commit, push, merge, publication ou promotion de modèle.

## Conception et état initial

Les deux pointeurs DVC existants décrivent les copies de livraison scientifique,
pas un pipeline d’apprentissage. Dans ce worktree, leurs sorties privées et la
configuration de remote locale sont absentes. Aucun remote n’a été supposé
accessible, configuré ou contacté ; aucune récupération des modèles n’a été lancée.

Les modules de préparation, d’entraînement, d’évaluation, les configurations et
les intégrations MLflow/Prefect/monitoring ont été examinés. Les trainers officiels
ont des conventions de sorties et des protocoles scientifiques protégés. Le
pipeline ajouté utilise donc un petit autoencodeur distinct et des données
procédurales locales. Il réutilise les dépendances CPU et leurs contraintes
existantes, sans modification de `src/`, `backend/app/`, `configs/`,
`pyproject.toml`, des pointeurs DVC ou des flows planifiés.

Le constat privé `mlops/local/dvc_pipeline/baseline.json` a été enregistré avant
les modifications : 1 944 fichiers scientifiques protégés dans le worktree
principal, 517 fichiers publics de son état courant, 467 fichiers initiaux du
worktree dédié et 17 conteneurs actifs. Il n’a pas été remplacé après intervention.

## Exécution réelle et résultats

Environnement constaté : Python 3.11.9, PyTorch 2.15.0+cpu, NumPy 2.3.5,
PyYAML 6.0.3, DVC 3.67.1, MLflow 3.16.1. L’interpréteur MLOps existant est
réutilisé en lecture seule ; le pipeline ne dépend pas de son package scientifique
editable et n’en modifie aucune installation. Les versions sont contrôlées
explicitement, avec calcul CPU et une thread par défaut.

Le premier `run.ps1 -Action repro` a exécuté les trois commandes du `dvc.yaml`
et créé `dvc.lock`. Les vérifications automatisées ont ensuite exécuté :

| Commande / scénario | Étapes réellement exécutées | Résultat |
|---|---|---|
| `dvc dag` | Aucune, lecture seule | Trois étapes liées et deux pointeurs officiels indépendants |
| `dvc repro --force --no-run-cache` | preprocessing, training, evaluation | Recalcul complet ; 24,12 s pour la référence mesurée |
| Deuxième `dvc repro`, sans changement | Aucune | Dix SHA et dates de modification inchangés ; 2,97 s |
| Seed training 42→43, puis `dvc repro` | training, evaluation | Prétraitement conservé ; poids différents |
| Quantile 0,95→0,90, puis `dvc repro` | evaluation | Poids conservés |
| Restauration exacte des paramètres | Aucune commande de stage | Résultats d’origine restaurés depuis le cache d’exécution |
| Modification contrôlée du fichier du modèle | training, evaluation | Dépendance de code correctement déclarée |
| Restauration exacte du code | Aucune commande de stage | État initial récupéré |
| Nouveau `dvc repro --force --no-run-cache` | preprocessing, training, evaluation | Dix sorties identiques octet pour octet ; 25,73 s |
| Dernier `dvc repro` | Aucune | Aucun recalcul |
| `dvc status dvc.yaml --json` | Aucune | `{}` |

Les temps sont des observations locales et non des garanties de durée. Les
paramètres et le code temporairement modifiés ont été restaurés exactement.
La preuve repose sur les reçus d’exécution de chaque étape, et non seulement
sur l’absence de différence numérique ou sur une restauration du cache.
Les deux recalculs complets désactivent explicitement le cache d’exécution.

DAG du pipeline, avec l’entrée de test/calibration directement issue du prétraitement :

```text
preprocessing ───────────────┐
      │                     │
      ▼                     ▼
   training ──────────► evaluation

mlops/dataset.dvc        (livraison indépendante, inchangée)
mlops/deployment.dvc     (livraison indépendante, inchangée)
```

Les données de développement comprennent 192 images procédurales 32×32 :
96 normales pour apprendre, 32 normales pour calibrer le seuil de démonstration,
64 tests indépendants dont 32 anomalies synthétiques. Les seeds de splits sont
distinctes, les contenus ne se chevauchent pas et aucune image MVTec n’est utilisée.

L’entraînement effectue six époques et **36 mises à jour Adam**. La variation
quadratique des poids est **0,69856249**, la loss initiale **0,0187973082** et la
loss finale **0,0043920153**. Il ne s’agit pas d’une copie de checkpoint.

Sur le test de développement : accuracy **0,90625**, AUROC **1,0**, F1
**0,9142857143**, avec 32 VP, 26 VN, six FP et zéro FN. Le seuil
**0,0045287320** est calculé uniquement sur les normales de calibration, avant
évaluation du test. Ces métriques sont explicitement préfixées `demo_` et ne
constituent aucun nouveau résultat MVTec ou des modèles industriels officiels.

Empreintes finales :

- Manifeste : `b5ff9bf81f2265063115bc5b15609694f6c851a4391850066a54e12aa5a22d1d`.
- Poids du petit modèle : `499383d93666e2ddb3722ad62b5eef41463a8eedca2541d84b3f661202f2c034`.
- Les dix SHA256 détaillés et les sorties textuelles des commandes figurent dans
  [`dvc_pipeline_verification.json`](dvc_pipeline_verification.json).

## Traçabilité, stockage et MLflow

Les dépendances et paramètres consommés sont déclarés dans `dvc.yaml` ;
`dvc.lock` contient leurs versions de contenu et celles des sorties. Les sorties
se trouvent uniquement sous `mlops/dvc_pipeline/work/`, ignoré par Git, et dans le
cache **copy** propre au worktree `.dvc/cache`. Les deux espaces de livraison
officiels ne sont ni dépendances ni sorties de ce nouveau pipeline.

Les métadonnées variables d’exécution — durée, UUID, état Git, versions — sont
conservées dans les reçus privés hors des dix sorties cachées. Cela permet de
tracer une durée réelle sans casser l’identité binaire des artefacts. Les fichiers
de pipeline restent non commités ; la provenance Git l’indique explicitement.

MLflow a réellement créé l’expérience **ResilientInspect-DVC-Pipeline-Demo** dans
la base séparée `mlops/local/dvc_pipeline/mlflow/tracking.db`. Le run
`5f44fc5c25a6413e9add5c48f3c99f0a` contient paramètres, manifeste, identité Git,
durées, loss, métriques et artefacts de développement. Deux appels de tracking
ont conservé un seul run terminé, avec la même empreinte. Le Registry de cette
base de démo reste vide. La base officielle conserve **30 runs et trois modèles**,
avec son SHA256 initial inchangé. Aucune promotion automatique.

L’interface MLflow préexistante n’est pas redirigée vers cette base. Une commande
facultative pour ouvrir une interface séparée est fournie dans le guide ; aucun
serveur MLflow supplémentaire n’a été lancé pendant la mission.

## Prefect et continuité des services

Le point d’entrée additionnel `prefect_flow.py` renvoie `disabled` par défaut,
avant tout lancement de sous-processus ou import Prefect. Son activation exige
`--enabled` et un interpréteur CPU/DVC explicite. Elle crée un flow manuel,
sans déploiement ni planning, et ne modifie pas les flows existants.

L’essai manuel a réellement terminé en `Completed`, run
`c4cc244d-54a8-4b81-8294-c58caf607719`. DVC a réutilisé les sorties à jour ; cet
essai n’a pas déclenché un nouvel entraînement. Les planifications existantes
restent à **3 600 s** pour le flow scientifique et **60 s** pour le monitoring.
Le mode par défaut désactivé est également vérifié par un test qui interdit
tout appel à `subprocess.run`.

Les contrôles finaux vérifient les trois scrapes Prometheus, Grafana, React sur
18180 et les **15 PyTorch / 14 ONNX prêts** du backend existant. Les 17 conteneurs
actifs au départ conservent leurs IDs et dates de démarrage. Aucune intervention
sur Oracle/8080, aucun redémarrage de service.

## Tests et non-régression

| Suite | Résultat final |
|---|---|
| Neuf tests du nouveau module | **9 réussis**, aucun échec ni skip |
| Backend API, portabilité, Compose, intégrité MLOps et politique CI | **86 réussis**, un avertissement MLflow existant |
| Orchestration Prefect existante | **19 réussis** |
| Scénarios DVC réels | Recalcul, cache, paramètres, dépendance de code et identité binaire vérifiés |
| Ruff du nouveau module | Succès |
| Vérification des métadonnées DVC existantes | 1 898 références, 15 checkpoints et 14 graphes ; succès |
| Contrôle Git des fichiers privés / artefacts | Succès, y compris fichiers non suivis non ignorés |
| SHA scientifiques avant/après | **1 944 identiques** |
| Fichiers initiaux du worktree dédié | **467 inchangés** |
| État du worktree principal | **517 fichiers initiaux et état Git non commité inchangés** |

Soit **114 tests pytest réussis**, complétés par les essais DVC, MLflow, Prefect
et les contrôles de services réels.

Les tentatives intermédiaires ne sont pas masquées :

- Le premier essai du nouveau test de lien a été ignoré faute de privilège Windows
  pour créer un symlink. Le test utilise maintenant une jonction Windows, sans
  privilège supplémentaire, et vérifie réellement le refus d’écriture hors du
  répertoire de démo ; aucun skip ne reste dans la suite finale.
- La première invocation directe des tests existants obtenait 79 réussites et
  sept erreurs de fixture de calibration. L’environnement partagé chargeait le
  package editable du worktree principal, alors que les fixtures calculaient les
  empreintes des sources du worktree dédié. `regression.py` lie désormais le
  package au checkout testé avant l’import, sans modifier l’environnement ou le
  code scientifique. La suite corrigée a obtenu les 86 réussites.
- Les tests de monitoring nécessitant les références privées/runtime absents de
  ce worktree n’ont pas été exécutés ici. Leur code est inchangé ; les services et
  leurs scrapes ont été vérifiés. Aucune CI distante n’est revendiquée.

## Fichiers et commandes

Fichiers racine créés : `dvc.yaml`, `params.yaml`, `dvc.lock`.
Le nouveau module `mlops/dvc_pipeline/` contient les trois étapes, le petit modèle,
les contrôles communs, recette, environnement, dépendances, wrapper PowerShell,
tracking, entrée Prefect facultative, vérificateurs et tests. S’ajoutent le guide
et les deux rapports `reports/experiments/dvc_pipeline_verification.{md,json}`.
La liste exacte est dans `created_files` du JSON joint. **Aucun fichier préexistant
n’est modifié**, et aucun fichier n’est staged automatiquement.

Commandes principales réellement exécutées, depuis le worktree dédié :

```powershell
$demoPython = 'C:/Users/nouhe/resilientinspect-ai/.venv-mlops/Scripts/python.exe'
./mlops/dvc_pipeline/run.ps1 -Python $demoPython -Action repro
& $demoPython -m dvc dag
./mlops/dvc_pipeline/run.ps1 -Python $demoPython -Action verify
./mlops/dvc_pipeline/run.ps1 -Python $demoPython -Action tests
./mlops/dvc_pipeline/run.ps1 -Python $demoPython -Action track  # exécuté deux fois
& $demoPython -m mlops.dvc_pipeline.regression
& $demoPython -m mlops.dvc_pipeline.preservation
& $demoPython scripts/ci/check_dvc_metadata.py
& $demoPython scripts/ci/repository_guard.py --include-untracked
& $demoPython -m ruff check --config ruff.toml mlops/dvc_pipeline
```

Les commandes DVC détaillées et leur sortie réelle sont dans le JSON, et les logs
bruts/JUnit dans `mlops/local/dvc_pipeline/`, ignoré par Git. Les tableaux, poids,
bases et autres artefacts privés ne sont pas ajoutés aux candidats Git.

## Limites et démonstration

L’identité binaire est prouvée sur cette machine Windows CPU et ces versions,
sans garantie entre autres processeurs, systèmes ou bibliothèques. Le dataset est
procédural et de développement ; les performances ne se transposent pas à MVTec.
Le remote local historique n’est pas configuré dans ce worktree, et le cache local
n’est pas une sauvegarde hors machine. Le pipeline reste rejouable sans remote
par génération déterministe des données et entraînement réel.

Le scénario chronométré en deux minutes, les paramètres, les commandes de
reproduction et la consultation MLflow facultative sont dans
[`mlops/dvc_pipeline/README.md`](../../mlops/dvc_pipeline/README.md).
