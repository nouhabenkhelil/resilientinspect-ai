# Sprint 3 — Observabilité, sauvegarde et résilience

Validation locale des 24–25 novembre 2026 (preuves horodatées en UTC), branche `feature/industrial-platform`, HEAD initial `70cdb954971e2561e7714b0908e1818ff530d796`. Aucun commit ni push. Aucune fixture n'est présentée comme inférence réelle.

## Fonctionnalités implémentées

- Logs JSON sur le portail et le worker, champs autorisés, identifiants de requête/corrélation/lot/item et durée ; exclusion des messages arbitraires, paramètres OIDC, mots de passe, cookies, JWT, images et textes d'exception. Les routes des métriques utilisent les templates, sans UUID/utilisateur/nom de fichier comme label.
- Métriques HTTP réelles compteur/histogrammes ; sondes HTTP science/gateway/Keycloak, SELECT 1 chronométré, agrégats SQL file/running/durée/retries/erreurs, espace du filesystem privé, heartbeat durable et inventaire 15/14. Une mesure absente reste indisponible, sans valeur inventée.
- Migration additive `cdd4d1bad73b` appliquée après `0f2e340aabb2`, table `service_heartbeats`. Compte `ri_observer` en lecture seule sur les tables opérationnelles ; pas de SELECT utilisateurs ni UPDATE items. Auth/session/OIDC et permissions existantes conservées.
- Compose observabilité séparé : observer privé, Prometheus `127.0.0.1:19090`, Grafana `127.0.0.1:13000`, versions/digests épinglés. Basic auth admin, token Bearer de scrape, `/api/metrics` masqué par Nginx ; aucun accès public au backend scientifique ni aux images.
- Six dashboards provisionnés : santé, API, lots, traitements/erreurs, PostgreSQL/stockage, moteurs. Huit règles configurables dans `deployment/operations/thresholds.yml`, générateur reproductible et tests promtool. Aucune destination de notification externe configurée.
- Operations Center intégré à System Monitor V3, mesures réelles et événements techniques ; accès admin/AI engineer, refus operator/auditor. Identité `frontend/DESIGN.md` conservée.
- Arrêt gracieux du worker et heartbeat SQL ; perte de connexion/verrou entraîne la sortie et permet le redémarrage contrôlé. Fencing, réservations atomiques, retries limités et sources scientifiques préservés.
- Sauvegardes chiffrées, SHA256/manifeste, rotation confinée et daemon Windows approuvé, cycles core quotidien et MLOps hebdomadaire ; restauration isolée réelle. Voir [stratégie](backup-strategy.md) et [rapport de restauration](restore-report.md).

## Tests réellement observés

| Vérification | Résultat observé |
|---|---|
| Backend portail : OIDC/session, RBAC/IDOR, fichiers, migrations, batch/worker/retries, nouvelles opérations | **58/58**, code final monté dans le conteneur de test ; base `portal_tests` exclusivement ; 31,80 s |
| Régression backend scientifique/Compose/provenance/ONNX | **70/70**, 79,60 s ; aucun entraînement ni export |
| React | **83/83**, 15 fichiers, `--maxWorkers=2` ; un premier lancement concurrent avait atteint un timeout, sans modification de tolérance/test |
| TypeScript, ESLint, build Vite | Passés |
| Chiffrement/tampering/extraction/lock/rotation sur fixtures temporaires | **5/5** |
| Promtool configuration/règles | Configuration valide, **8 règles**, déclenchement et résolution testés sur séries synthétiques |
| Prometheus réel | Deux cibles authentifiées `up`, sondes/SQL/modèles réels ; 17 requêtes de dashboard acceptées |
| Grafana navigateur réel | Login admin puis **6 dashboards / 17 panneaux visibles**, aucune erreur JavaScript |
| V3 navigateur réel | Quatre comptes Keycloak, PKCE S256, cookies serveur, déconnexion révoquant l'accès ; Operations 200 admin/engineer, 403 operator/auditor ; anonyme 401 et métriques portail 404 |
| Restauration : navigateur réel | Même matrice des quatre rôles ; neuf inspections de l'opérateur retrouvées après connexion ; UUID conservés |
| Worker isolé réel | SIGTERM, alerte inactive puis firing/résolue, SIGKILL et reprise ; une image réelle T2/ONNX récupérée, score/seuil/décision/release exactement égaux à l'original |
| PostgreSQL isolé réel | Arrêt de la copie, alerte PostgreSQL firing puis résolue après redémarrage ; heartbeat et reconnexion worker retrouvés |
| Gateway isolée réelle | Alerte firing pendant l'arrêt de la copie, puis aucune alerte restante après redémarrage du portail isolé |
| Sauvegarde/restauration métier réelle | 5 utilisateurs, 11 inspections, 10 lots, 77 items/fichiers SHA256, releases identiques ; readiness initiale 674,2 s |
| MLOps | Archive 2,745 Go authentifiée, SQLite `ok`, 3 modèles enregistrés, 1 687 fichiers DVC, 431 artefacts |
| Provenance scientifique et Git | SHA256 des 40 sources, preuves Windows/Linux et 15 graphes, parités 14 admises + refus T1/bottle vérifiés ; garde dépôt passée |

La prédiction réelle récupérée porte sur une image autorisée déjà présente dans la sauvegarde, sans nouvelle acquisition MVTec : **une seule image recalculée avec succès** pendant ce Sprint 3, moteur T2/ONNX. Score `0.00003255931005696766`, seuil `0.00017796678002923727`, décision `normal`, deuxième réservation. Durée moteur observée `3358.981778999805 ms` ; intervalle SQL entre `item.recovered` et `item.completed` **9,945804 s**. Cette mesure sous contention et chargement à froid n'est pas un benchmark p50/p95. La validation PostgreSQL a réutilisé ce résultat réussi, sans nouvelle inférence.

Le premier laboratoire utilisait un scrape de cinq secondes, inférieur au budget possible des sondes. Lors de la panne SQL, la collecte pouvait expirer. Le budget du laboratoire est corrigé (scrape 10 s / timeout 8 s), avec connexions SQL dédiées sans pool persistant, `connect_timeout=2 s`, `statement_timeout=2 s`, `lock_timeout=1 s` et timeout TCP de 3 s. Le nouveau test SQL vérifie réellement l'interruption d'une requête lente puis une connexion neuve. La panne PostgreSQL a ensuite déclenché et résolu son alerte avec la cible de scrape disponible. La collecte opérationnelle n'affecte pas les sources scientifiques.

**État final contrôlé : onze services applicatifs V2/V3/observabilité actifs**, avec healthchecks Docker sains lorsqu'ils existent ; readiness et APIs Grafana/Prometheus vérifiées. V2 `18080`, API V2 `8001`, V3 `18180`, Keycloak `18585`, Prometheus `19090`, Grafana `13000`, tous publiés uniquement sur `127.0.0.1`. Aucun port publié pour PostgreSQL, portal, worker, observer ou science V3. Les trois services Python V3 (portal/worker/observer) sont liés aux **20 fichiers Python finaux** par SHA256 et utilisent l'image `sha256:37c540d6df7038e40fb21f7023639007f44f0aedfde9b8952b4c72862d22a69d`. Les versions Python/Torch/NumPy/sklearn/torchvision/Pillow/ONNX/ORT des deux services scientifiques correspondent aux preuves Linux conservées. T1/bottle ONNX a été réellement refusé HTTP **503 `onnx_unavailable`**, sans repli, après le dernier redémarrage.

Le laboratoire a été arrêté après validation pour libérer les ressources. Ses **trois volumes sont conservés**, ainsi que ses fichiers de configuration privés et ses preuves ; aucune suppression. Les huit règles ont été testées sur séries synthétiques ; worker, PostgreSQL et gateway ont en plus été observés réellement en firing puis résolus. Les autres situations (disque plein, charge soutenue, partition réseau) ne sont pas revendiquées comme pannes physiques testées.

Sauvegarde core finale : `core-20261124T225448Z-c4430b.ri3`, **43 479 076 octets**, durée totale **67,755 s**, fenêtre jusqu'à reprise vérifiée **64,007 s** ; authentification et **94 fichiers** du manifeste vérifiés. Elle comprend les références des images Docker, le patch Git et les sources opérationnelles nécessaires, en plus des données/configurations privées. La sauvegarde initiale reste celle ayant servi à la restauration complète ; les données métier n'ont pas été écrasées par les essais du laboratoire.

Daemon Windows constaté actif, second lancement refusé comme doublon, journal sans erreur ; prochaine échéance core **25 novembre 2026 22:55:55 UTC**, MLOps **1 décembre 2026 22:18:54 UTC**, à condition que le daemon/session/PC restent actifs. La récurrence sur 24 h n'a pas été observée pendant une journée entière : échéancier activé, sans prétendre avoir déjà exécuté une seconde journée.

## Commandes PowerShell

Les services de base doivent déjà être actifs ; les secrets restent dans `deployment/industrial/local/` ignoré. Pour une reprise préparée, sans recréer PostgreSQL :

```powershell
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml build portal
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml up --no-deps migrate
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml up -d --no-deps portal worker web
docker compose -f deployment/operations/compose.yml up -d
.venv-ops/Scripts/python.exe deployment/operations/verify_observability.py
node deployment/operations/operations-qa.mjs
node deployment/operations/dashboards-qa.mjs
./deployment/operations/start-backups.ps1
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml ps
docker compose -f deployment/operations/compose.yml ps
```

Le provisionnement initial du compte SQL observateur exige le secret en fichier, sans valeur sur la ligne de commande :

```powershell
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml run --rm --no-deps -v "${PWD}/deployment/industrial/local/observability/secrets:/run/secrets:ro" migrate python -m portal.provision_observer
```

## Git et limites avant Internet

Modifications du Sprint 3 : `services/portal/portal/{telemetry,operations,operations_models,provision_observer}.py`, middleware/app/security/worker, migration heartbeat, tests Operations, dépendance prometheus-client ; Compose industriel, Nginx, Operations React et tests ; `deployment/operations/` et cette documentation. Les modifications préexistantes de `.env.example`, Nginx, migration env et app sont conservées et étendues ; le rapport `deployment/reports/onnx-http.json` et les trois fichiers `reports/experiments/ci_cd_*` sont préservés. Sources scientifiques, `frontend/DESIGN.md`, Compose V2, poids, seuils et calibrations inchangés.

Les fichiers privés, captures, archives, dumps, images MVTec, checkpoints, ONNX et environnements virtuels restent exclus de Git. La liste exacte des **52 fichiers candidats**, incluant les modifications préexistantes, est dans `deployment/industrial/local/observability/publish-files.txt` ; rien n'est commité ou poussé. Les trois rapports CI préexistants, `.env.example` et `onnx-http.json` sont vérifiés identiques octet pour octet à la baseline. Les modifications préexistantes app/migration/Nginx sont étendues par ce sprint et couvertes par les régressions.

Les risques de production demeurent : HTTP local, Keycloak start-dev/H2, secrets de développement et politiques MFA/TLS, dimensionnement mémoire/charge, rétention et seuils d'alerte à ajuster sur une période réelle, absence de routage de notifications, sauvegardes sur le même PC et clé sans escrow hors machine. Le daemon dépend d'une session Windows active et n'est pas un service de production. Le redémarrage global Docker, autorisé séparément après HTTP 500, est un incident observé ; son origine n'est pas définitivement établie. Aucun déploiement Internet ni sprint suivant.

Le contrôle automatique a refusé le nettoyage d'un dossier temporaire privé avec le motif « blocked by policy ». Aucun contournement : le fichier SQLite temporaire reste en place, et les connexions SQLite sont désormais fermées explicitement.
