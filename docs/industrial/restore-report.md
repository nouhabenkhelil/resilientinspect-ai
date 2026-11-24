# Restauration réelle Sprint 3 — 24 novembre 2026

## Sauvegardes vérifiées

| Cycle | Archive initiale | Octets chiffrés | Acquisition |
|---|---|---:|---:|
| Core | `core-20261124T221323Z-a2837d.ri3` | 42 946 596 | 181,368 s |
| MLflow/DVC | `mlops-20261124T221700Z-d405dd.ri3` | 2 745 036 836 | 114,484 s |
| Core final, avec sources opérationnelles et références d'images | `core-20261124T225448Z-c4430b.ri3` | 43 479 076 | 67,755 s |

Les archives et clés restent privées et hors Git. Le déchiffrement GCM, le SHA256 du ciphertext et tous les fichiers du manifeste intérieur ont été vérifiés. MLflow : `PRAGMA quick_check = ok`, trois modèles enregistrés ; inventaires DVC : 1 687 fichiers, artefacts MLflow : 431. Aucun entraînement, export scientifique ou écriture dans les stores sources.

## Destination et fidélité

Projet neuf `resilientinspect-recovery-51695ebbc1` ; volumes `..._postgres`, `..._idp`, `..._images`, conservés. PostgreSQL et Keycloak de service n'ont pas été utilisés comme destinations de restauration. Le dump a été importé dans une base vide ; les snapshots JSON métier ont été comparés intégralement, avant adaptation d'URLs.

Résultat vérifié : **5 utilisateurs, 11 inspections, 10 lots, 77 items et 77 fichiers privés**, chacun correspondant au SHA256 PostgreSQL. Les métadonnées et versions des releases scientifiques sont identiques. La base de service contenait 67 items complétés et 10 annulés ; ce comptage ne signifie pas que le Sprint 3 a recalculé 67 prédictions.

Adaptations uniquement dans la copie : issuer `localhost:18585` → `localhost:18685`, redirect URI client vers `localhost:18680`, identifiants SQL dédiés. Les UUID/sub/propriétaires restent identiques. Le navigateur a exécuté les quatre connexions OIDC Code/PKCE, la matrice de permissions Operations et les déconnexions ; l'opérateur retrouve ses **neuf inspections**. Modèles affichés : 15 PyTorch / 14 ONNX ; aucune erreur JavaScript.

Temps constaté depuis la création du dossier de restauration jusqu'aux probes HTTP prêtes : **674,2 secondes**, incluant les reprises de diagnostic. Ce n'est ni une moyenne de production ni un objectif contractuel. Un premier probe PostgreSQL avait détecté le serveur temporaire d'initialisation : le script attend maintenant le serveur TCP final et refuse une destination peuplée. Keycloak froid a dépassé la première fenêtre de 180 s ; la finalisation a revérifié la copie existante sans réimporter la base ni recopier les volumes.

## Incidents de disponibilité pendant les essais

Docker Desktop a renvoyé HTTP 500 pendant la construction parallèle et le lancement du laboratoire. WSL était limité à 4 Go de RAM et 2 Go de swap ; aucune preuve ne permet d'attribuer définitivement la cause à la seule mémoire. Après autorisation distincte de l'utilisateur, le redémarrage global a été effectué ; V2 et les autres conteneurs précédemment actifs ont été remis en marche. Aucun volume n'a été supprimé ou réinitialisé. Le Keycloak de restauration a ensuite été arrêté, et les constructions rendues séquentielles.

Les images scientifiques relancées font leur chargement initial et leurs contrôles de provenance habituels. Aucune vérification SHA256 n'a été désactivée. Les premières tentatives de reprise du worker isolé ont reçu `inference_unavailable` pendant cette indisponibilité : elles ne sont pas comptées comme prédictions réussies. Les retries sont restés limités à trois.

Résultats définitifs : worker SIGTERM puis SIGKILL récupéré ; alerte WorkerInactive réellement déclenchée et résolue. PostgreSQL arrêté uniquement dans la copie, alerte réellement déclenchée et résolue, worker reconnecté après retour de la base. Une seule image réelle a été recalculée avec succès : T2/ONNX, score `0.00003255931005696766`, seuil `0.00017796678002923727`, `normal`, release identique à l'original. Intervalle durable `item.recovered` → `item.completed` : **9,945804 s**, dont durée moteur observée **3358,981779 ms**. La reprise de la validation SQL n'a pas répété cette inférence réussie.

Le premier scrape du laboratoire était trop court pour la somme des budgets SQL/HTTP ; il a été corrigé à 10 s / timeout 8 s, avec connexions SQL fraîches et délais natifs bornés. Le test PostgreSQL a ensuite passé sans dépendre d'une connexion périmée. La sauvegarde finale a vérifié 94 fichiers intérieurs et la reprise des services en **64,007 s** ; elle ne remplace pas la preuve de restauration complète de la première archive. Les preuves détaillées restent dans `deployment/industrial/local/observability/` ignoré.

La gateway de copie a également déclenché puis résolu son alerte après remise en marche. Le laboratoire a été arrêté après ces contrôles, avec ses trois volumes conservés pour revue. Les services V2/V3 et l'observabilité de service restent actifs.

## Limites

La restauration métier/Keycloak/images est réelle sur cette machine. La copie hors machine et la récupération après perte physique du PC ne sont pas testées. La sauvegarde MLOps a été authentifiée et sa base SQLite vérifiée ; elle n'a pas été restaurée au-dessus d'un service MLflow actif. Le coffre de clé séparé doit être exporté et conservé selon une procédure autorisée avant toute promesse de reprise après perte du disque.
