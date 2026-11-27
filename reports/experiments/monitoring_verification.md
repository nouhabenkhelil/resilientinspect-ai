# Vérification du monitoring MLOps — 27 novembre 2026

Le monitoring local est opérationnel dans le périmètre vérifié ci-dessous.
Prometheus/Grafana existants sont réutilisés ; un collecteur externe et un flow
Prefect séparé ont été ajoutés. Les appels directs au backend qui contournent le
proxy optionnel ne sont pas comptés par ce proxy. Les prédictions du portail sont
collectées indépendamment en lecture seule dans PostgreSQL.

Branche conservée : `feature/mlops-prefect-orchestration`. HEAD initial et final :
`630da12a552ab02d2e39c7fea764fb831cf25a58`. Le dépôt contenait déjà des modifications
frontend, Prefect, CI, portail et staging ; elles n’ont pas été écrasées. Aucun
commit, push, merge ou changement de branche pendant cette mission.

## Constats et résultats réels

| Vérification | Résultat constaté |
|---|---|
| Prometheus | Trois cibles réellement `up` : portail, observer, collecteur MLOps |
| Source Grafana `ri-prom` | Health `OK`, requête Prometheus authentifiée réussie |
| Dashboards Grafana | Trois dashboards visibles, 27 panneaux, 27 requêtes avec données mesurées, aucune erreur navigateur |
| Instrumentation réelle | Delta de 143 requêtes HTTP ; classes 2xx/4xx/5xx observées |
| Prédictions réelles | 30 validations B0/bottle PyTorch et une ONNX ; uniquement validation normale figée |
| Refus ONNX T1/bottle | HTTP 503 `onnx_unavailable`, sans fallback |
| Drift validation PyTorch | Référence 42 scores, fenêtre 30 scores, KS 0,119047619, écart de taux 0,047619048 ; état `stable` |
| Drift ONNX à un exemple | `insufficient_data`, aucune conclusion statistique inventée |
| Drift contrôlé | Fixture de 42 scores synthétiques : stable puis décalage détecté ; origine `synthetic` explicite |
| Alertes en conditions réelles Prometheus | Dix règles observées `firing` sur séries synthétiques, puis dix résolues ; infrastructure réelle non falsifiée |
| Règles promtool | 12 scénarios, 24 assertions de déclenchement/résolution, succès |
| Persistance après redémarrage | Collecteur seul redémarré ; 296 lignes, empreinte `fad49bc9e813cd180592b287963940a3b61e9a8e588f90deec0a9cf9993b8c73` identique avant/après ; scrape rétabli |
| Confidentialité SQL | Lecture de la vue autorisée ; lecture de users/inspections et UPDATE batch interdits ; transaction read-only |
| Préservation scientifique | 1 944 SHA256 identiques au constat avant modification |
| Préservation des services | IDs et dates de démarrage des 16 conteneurs préexistants identiques |
| Sécurité du dépôt | Repository guard sur fichiers suivis et non ignorés réussi ; aucun modèle, dataset, secret ou base ajouté |

Les comptes correspondent à des périmètres différents : les 296 lignes concernent
la rétention totale de la base dédiée, y compris l’historique sur sept jours ; les
statistiques et comparaisons portent sur une fenêtre de 24 heures et une origine
à la fois. Les compteurs HTTP se réinitialisent normalement au redémarrage.

Une alerte **réelle** `MLOpsHighRAM{source="production"}` a été observée : la mémoire
Windows dépassait le seuil configuré de 90 %. Elle n’a pas été masquée pour rendre
la démonstration artificiellement verte. Aucun service utilisateur n’a été arrêté
pour réduire cette charge. Les alertes synthétiques ont, elles, toutes été résolues.
Le JSON joint conserve les valeurs et alertes au moment de sa génération.

## Versions, accès et orchestration

- Python Windows 3.11.9 ; environnement dédié `.venv-monitoring` : psutil 7.2.2,
  PyYAML 6.0.4, pytest 9.2.0 et dépendances verrouillées.
- Collecteur : image locale existante `resilientinspect-portal:local`, utilisateur
  non privilégié `portal`, Python 3.11.9, psycopg 3.3.9, prometheus-client 0.26.0.
  L’identifiant exact de l’image est conservé dans le JSON joint.
- Prometheus 3.16.0 : `127.0.0.1:19090` ; Grafana 13.3.2 : `127.0.0.1:13000`.
- Nouveau collecteur/proxy : `127.0.0.1:19108`, authentifié ; aucune exposition
  sur toutes les interfaces. Les secrets sont dans les répertoires privés ignorés.
- Prefect 3.9.5 sur `127.0.0.1:4200` : nouveau déploiement
  `resilientinspect-monitoring-drift/local-monitoring`, intervalle 60 secondes,
  concurrence 1, Africa/Lagos. Des exécutions planifiées ont réellement terminé
  en `Completed` ; l’identifiant du dernier run vérifié figure dans le JSON.
- Le déploiement scientifique `local-readonly` conserve son intervalle de 3 600
  secondes et reste actif. Son code et son runner n’ont pas été remplacés.
- Les erreurs intermédiaires pendant l’installation du collecteur restent dans
  l’historique Prefect. Le stockage SQLite partagé Windows/Linux a été remplacé
  par un volume Linux ; les runs ultérieurs réussissent. Aucune suppression des
  échecs historiques pour présenter une réussite artificielle.
- L’application industrielle reste sur **18180**, avec FastAPI privé sur
  `science:8000`. Les ports historiques 18080/8001/5000 n’étaient pas disponibles
  au constat initial ; aucune migration ni réactivation de ces services n’a été
  imposée. Aucune intervention Oracle/8080.

## Tests exécutés

| Suite | Résultat |
|---|---|
| `mlops/monitoring/tests` | 18 réussites : confidentialité, déduplication, rétention, groupement, valeurs invalides, drift stable/décalé, données insuffisantes, référence absente, unités et référence figée |
| `mlops/orchestration/tests` | 19 réussites |
| Backend API, portabilité, Compose et `mlops/tests` | 66 réussites ; un avertissement MLflow existant sur les annotations de type |
| `scripts/ci/tests` | 20 réussites |
| Promtool | 12 scénarios / 24 assertions réussis |
| Playwright Grafana | Trois dashboards et 27 panneaux vérifiés avec leur source réelle |

Soit **123 tests pytest réussis**, complétés par les vérifications réelles de
scraping, inférence, dérive, alertes, droits, navigateur et persistance.
Une première commande de test utilisait un `PYTHONPATH=src;.` inadapté au mapping
du package installé ; elle échouait à la collecte. La commande corrigée, sans cet
override, a exécuté les 66 tests avec succès, sans modifier l’environnement scientifique.
Aucun résultat d’exécution CI distante n’est revendiqué.

## Fichiers et preuves

Trois fichiers préexistants ont été modifiés par cette étape :

- `.gitignore` : ajout de l’environnement de monitoring isolé.
- `deployment/operations/prometheus.yml` : ajout du job authentifié, avec
  conservation du label d’origine exporté (`honor_labels: true`).
- `deployment/operations/alerts.yml` : ajout du groupe de dix règles MLOps.

Nouveaux fichiers : module `mlops/monitoring/` (configuration, Compose, bootstrap,
collecteur/proxy, stockage, référence, drift, flow, démonstration, dashboards,
tests et vérifications), trois copies de provisioning
`deployment/operations/dashboards/ri-mlops-*.json`, ce rapport et son JSON.
La **liste exacte**, sans les modifications qui préexistaient à la mission, est
dans `existing_file_changes` et `new_files` du
[`monitoring_verification.json`](monitoring_verification.json).

Preuves privées, ignorées par Git :

- `mlops/local/monitoring/baseline.json` : constat avant modification.
- `mlops/local/monitoring/runtime/*-verification.json` : inférence, alertes,
  règles, navigateur, persistance, droits SQL, préservation et tests.
- `mlops/local/monitoring/runtime/browser/ri-mlops-*.png` : captures Grafana réelles.
- `mlops/local/monitoring/runtime/unit-tests.xml` : résultat de la suite dédiée.
- `mlops/local/monitoring/runtime/reference.json` et `.sha256` : référence figée.
- `mlops/local/monitoring/runtime/drift.json` et `.html` : rapport courant.

Les poids, calibrations, métriques historiques, données MVTec, preuves Windows/Linux,
code scientifique et base MLflow n’ont pas changé. Les fonctions React et les
contrats publics FastAPI sont préservés. Les volumes Prometheus/Grafana existants
sont conservés ; leur redémarrage n’a pas été exécuté pour respecter la continuité
des services préexistants. La persistance du nouveau stockage a été testée réellement.

## Limites et démonstration

La référence contient des **normales de validation**, pas une estimation du mélange
réel des défauts en production. Les seuils KS 0,30 et écart de taux 0,20 sont une
politique opérationnelle configurable, choisie sans optimiser le test officiel.
Un drift est un signal à examiner, pas une preuve de dégradation d’accuracy.
Sans labels de production, aucun accuracy/AUROC/F1 n’est publié ; sans
caractéristiques d’image collectées, aucun drift des entrées n’est prétendu.

Les ressources Windows/Docker sont échantillonnées toutes les 60 secondes ; les
scrapes et la collecte SQL toutes les dix secondes. Les runners locaux doivent
rester actifs ; aucun service de démarrage Windows n’a été installé. La collecte
SQL est limitée à 10 000 résultats sur sept jours, avec alerte de troncature.
Le proxy optionnel n’a pas été substitué au chemin d’inférence existant.
Aucun message ni alerte n’a été envoyé à un service externe.

Le guide de démarrage, les commandes reproductibles, l’arrêt sans perte de données,
le retrait ciblé et le **scénario de démonstration en 2–3 minutes** figurent dans
[`mlops/monitoring/README.md`](../../mlops/monitoring/README.md).
