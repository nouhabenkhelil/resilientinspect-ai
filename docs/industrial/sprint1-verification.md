# Industrial Platform V3 — rapport Sprint 1

Vérification locale du **24 novembre 2026**, branche `feature/industrial-platform`, base Git `c0b418e`. **Validation de bout en bout du Sprint 1 réussie**, y compris expiration naturelle et persistance après le seul redémarrage PostgreSQL explicitement autorisé. Aucun commit, push ou accès Internet public effectué.

## Ce qui est implémenté

- BFF FastAPI indépendant, OIDC Authorization Code + PKCE S256, vérification RS256/JWKS et claims, sessions opaques PostgreSQL, cookies HttpOnly/Secure en production, CSRF, logout et révocation.
- Quatre rôles, contrôles SQL par inspection, partage explicite en lecture, administration limitée, profil et audit.
- PostgreSQL persistant, rôle applicatif distinct du migrateur, migration Alembic `d1c1799c7017` effectivement appliquée à `portal` et `portal_tests`.
- Historique serveur paginé/filtré, références checkpoint/calibration SHA256 et corrélation des UUID gateway/science ; images et base64 exclus du stockage métier.
- Quotas transactionnels, concurrence bornée, validation réelle des images, délais, erreurs assainies et journalisation sans query OIDC.
- Frontend industriel optionnel conservant le Studio 2.0, connexion, profil/rôle, navigation autorisée, états 401/403, historique persistant, administration/audit. Cache mémoire invalidé au changement de compte et réponses tardives rejetées.
- Compose distinct et images séparées. Le démonstrateur 18080 et Oracle 8080 restent en service.

Voir [architecture.md](architecture.md) et [security-threat-model.md](security-threat-model.md) pour la matrice de permissions, les frontières et les limites.

## Résultats effectivement exécutés

| Contrôle | Résultat observé | Portée |
|---|---|---|
| Tests portail sur PostgreSQL `portal_tests` | **27 passés** lors de l'implémentation précédente | Résultat conservé ; fixtures SQL non relancées car elles tronquent les données de leur base isolée. Aucun changement au service portail pendant cette finalisation |
| Tests frontend | **75 passés**, 12 fichiers | 70 existants + 5 nouveaux contrôles client/CSRF/401/cache d'identité |
| Régression backend/déploiement/ONNX/portabilité ciblée | **70 passés**, 49,44 s lors de la finalisation | `test_backend_api.py`, `test_compose_deployment.py`, `test_onnx_export.py`, `test_deployment_portability.py` ; fixtures isolées |
| Garde CI et politique de dépôt | **20 passés** | Inclut refus des secrets/données/poids/dossiers industriels privés |
| TypeScript, ESLint, build démo | Réussis | `npm run build` comprend `tsc --noEmit` |
| Build industriel authentifié | Réussi dans Docker | `VITE_PORTAL_MODE=true`, API `/api` |
| Contrats FastAPI/TypeScript | Réussis | OpenAPI réel du backend et six formes de réponse ; pas d'inférence revendiquée |
| Données publiques | Réussies | 15 agrégats d'expériences et 6 agrégats de benchmarks existants cohérents ; aucun benchmark inventé/recalculé |
| Ruff, actionlint, `git diff --check` | Réussis | Nouveau service inclus au lint et job PostgreSQL ajouté au workflow ; exécution GitHub distante non effectuée |
| Garde dépôt incluant non suivis | Réussie | Aucun secret/poids/ONNX/base/MVTec admissible dans les fichiers candidats ; ne certifie pas l'historique Git entier |
| Alembic upgrade + `alembic check` | Réussis | Révision appliquée ; aucun écart de schéma détecté dans la base isolée |
| Autorisations SQL | Réussies | Le rôle `ri_app` ne peut supprimer audit, versions et catégories |
| HTTP anonyme réel du portail | **7 × 401** | `/auth/session`, `/status`, `/model/metadata`, `/inspections`, `/admin/users`, `/audit`, `/readiness`, via Nginx sur 18180 |
| Liveness réelle | HTTP 200 | `/api/health` renvoie uniquement `status=ok, service=portal` |
| Admissions du moteur industriel privé | **15 PyTorch / 14 ONNX** | Lecture réelle de son `/health` par `docker compose exec`, sans inférence supplémentaire |
| Démonstrateur historique | HTTP 200 sur 18080 ; **15/14** sur son API 8001 | Compose historique inchangé |
| Oracle | Port 8080 toujours en écoute | Aucun arrêt ni changement de configuration |
| Sources/preuves existantes | **40 empreintes de code conformes** | Deux preuves PyTorch Windows/Linux, 15 bindings ONNX et 30 preuves de parité, hashes latéraux et graphes vérifiés |
| T1/bottle ONNX | **HTTP 503 `onnx_unavailable` réellement reçu via V3** | Inspection failed enregistrée ; aucun repli silencieux ; parité refusée existante conservée sur les deux OS |
| Logs conteneurs | **0 correspondance** avec les secrets configurés ; **0 JWT** détecté ; **0 correspondance** pour 5 valeurs sensibles dynamiques du parcours réel | Code OIDC, state, cookie flow, cookie session et CSRF vérifiés en mémoire sans persistance de leurs valeurs |
| Modifications préexistantes | **5 fichiers préservés par SHA256** | Détails ci-dessous |

Les 27 tests serveur couvrent identité valide et claims invalides, état/cookie/redirect, signature incorrecte et algorithme refusé, fournisseur indisponible, sessions expirées/révoquées/inactives, quatre rôles, IDOR, partage explicite, refus d'écriture auditor, CSRF, suspension/révocation admin, extension/contenu/dimensions/taille, destination fixe, absence de repli sur erreur upstream, quotas concurrents, baux, privilèges SQL, logs et configuration fail-closed. Les résultats d'inférence de ces fixtures ne sont pas des résultats scientifiques.

Les preuves et mesures antérieures restent valides ; aucune exportation, recalibration, réentraînement ou nouvelle parité numérique officielle n'a été exécuté. **165 tests ont été réexécutés pendant la finalisation** (75 frontend, 70 régression, 20 CI). Les 27 tests SQL précédents restent documentés séparément ; le total historique de 192 n'est pas présenté comme 192 tests nouvellement exécutés.

## Validation réelle de bout en bout

La commande précédemment refusée avec `--restart-postgres` n'a pas été relancée. Le parcours initial a été exécuté **sans cette option**, conformément à la nouvelle consigne. Deux essais se sont arrêtés au sélecteur du message Keycloak invalide, avant toute prédiction ; le message réel a été observé et le sélecteur QA corrigé. Le parcours suivant est passé intégralement : **8 réponses de prédiction/visualisation et 11 groupes de contrôles**, sans erreur JavaScript relevée. Aucune modification de l'application ni des modules scientifiques n'a été nécessaire.

| Contrôle réel Chromium/API | Observation |
|---|---|
| Connexion invalide | Mot de passe incorrect refusé par le vrai Keycloak |
| Code OIDC + PKCE | Paramètres réels `response_type=code`, `code_challenge_method=S256`, challenge/state/nonce présents ; callback et session valides |
| Comptes/rôles | admin, ai_engineer, operator, auditor et second opérateur réellement connectés |
| Cookie et stockage | Cookie opaque HttpOnly, SameSite=Lax ; invisible à `document.cookie` ; aucune clé token/session/CSRF/inspection dans localStorage/sessionStorage |
| Inférence anonyme | **POST `/api/predict` et `/api/predict/visualize` : 401** |
| IDOR | Second opérateur et auditor sans partage : **404** sur l'inspection du premier opérateur |
| Partage autorisé | Admin accorde explicitement la lecture ; auditor obtient ensuite **200** sur cette inspection |
| Écriture auditor | Prédiction refusée **403** |
| Administration/readiness | Opérateur refusé **403** ; engineer autorisé sur readiness **200** ; écran admin réservé vérifié |
| CSRF et upload | POST sans jeton : **403** ; faux PNG : **400** |
| Révocation | Sessions du second opérateur révoquées via admin ; endpoint **401** et retour UI à la connexion |
| Déconnexion | Session BFF révoquée, endpoint **401**, parcours end-session Keycloak atteint et confirmation traitée |
| Expiration naturelle | **605 s sans requête**, puis **401 `session_expired`** avec l'identifiant opaque original ; écran de connexion réapparu. Aucune modification d'horloge ou de session par SQL |
| Espaces Studio | Smart Inspection et explications, Comparison Lab avec deux moteurs réels, Model Analytics/Performance Engineering, System Monitor, Historique, profil, administration, audit et écran 403 vérifiés |
| Responsive | Historique desktop 1440 px/mobile 390 px capturé et inspecté ; aucun débordement horizontal de la page, tableau défilant |
| Reconnexion | Nouvelle connexion OIDC dans un contexte neuf ; **8 inspections completed antérieures** retrouvées par UUID/requête et consultables dans l'historique |

Image réelle : `data/raw/mvtec_ad/bottle/train/good/002.png`, SHA256 `7de0414f1744aaf5cec488928ee3b761509e4bad4f607dc4f6d41ad7862dab69`, vérifié avant exécution. Pour chaque couple, `/predict` et `/predict/visualize` V3 ont répondu 200. Quatre appels de référence supplémentaires au backend scientifique V2 inchangé ont donné les résultats suivants :

| Modèle/catégorie | Moteur | Score réel | Seuil officiel reçu | Décision | Écart V3 / moteur V2, même moteur |
|---|---|---|---|---|---|
| B0/bottle | PyTorch | 0.16482834838239885 | 0.20367741357625985 | normal | **0 exact** |
| B0/bottle | ONNX Runtime | 0.16482830760864223 | 0.20367741357625985 | normal | **0 exact** |
| T2/bottle | PyTorch | 0.00003256561467424035 | 0.00017796678002923727 | normal | **0 exact** |
| T2/bottle | ONNX Runtime | 0.00003255931005696766 | 0.00017796678002923727 | normal | **0 exact** |

Les différences PyTorch/ONNX visibles dans ce tableau sont celles des moteurs existants ; aucune tolérance ou calibration n'a été modifiée. Les versions checkpoint/calibration ont été comparées aux métadonnées réelles et aux lignes SQL. Pour T2 ONNX, l'explication utilise le moteur PyTorch existant avec `explanation_score_coherent=true`, conformément au contrat scientifique antérieur.

Lecture SQL réelle : **11 inspections**, dont **10 completed** (8 Smart Inspection + 2 Comparison Lab) et **1 failed** (T1/bottle ONNX), 5 utilisateurs, 2 références de versions et révision `d1c1799c7017`. Les huit lignes Smart Inspection ont été comparées champ par champ aux réponses HTTP : scores, seuils, décisions, moteurs, SHA256 et request_id identiques. L'empreinte d'image est NULL ; aucune image/base64 n'est stockée.

L'utilisateur a ensuite **explicitement autorisé les sauvegardes et le seul redémarrage PostgreSQL ciblé**, après inspection de la procédure [postgres-restart-review.md](postgres-restart-review.md). L'expiration naturelle s'est terminée avant cette interruption. Aucun reset de base, de Keycloak ou de volume n'a été effectué.

Sauvegardes réelles : `portal.dump` **36 583 octets**, `portal_tests.dump` **28 254 octets**, et `globals.sql` conservés dans le dossier privé ignoré `deployment/industrial/local/backups/20261124-151517/`. Les deux archives custom sont lisibles par `pg_restore --list` ; empreintes SHA256 enregistrées dans le relevé local. Leur contenu sensible n'a pas été affiché. **Une restauration complète n'a pas été exécutée** et nécessiterait une autorisation distincte.

Le 24 novembre à **15:15 WAT (Africa/Lagos)**, seul `postgres` du projet industriel a été redémarré avec la commande inspectée. Volume conservé : `resilientinspect-industrial_postgres-data`. Le snapshot métier avant/après est **strictement identique** : 11 inspections avec leurs résultats, dates, propriétaires et corrélations, références de modèles, grants et rôles/suspensions des utilisateurs ; même révision Alembic. Aucun calcul n'était actif. Les champs d'activité des sessions et les nouveaux audits ne font pas partie de ce snapshot métier car ils évoluent normalement lors des requêtes.

Une session navigateur réelle est restée en mémoire pendant l'interruption : **même session serveur encore valide après redémarrage**, 9 inspections de son périmètre retrouvées à l'identique, historique UI consultable sans reconnexion. Les 11 inspections globales sont conservées. Les compteurs restent **15 PyTorch / 14 ONNX** ; V2:18080 et V3:18180 répondent toutes deux **200** après le redémarrage. Le scan des 5 valeurs sensibles dynamiques du parcours a donné **0 correspondance** dans les logs.

## État final des conteneurs

| Service industriel | État observé | Port hôte |
|---|---|---|
| postgres | running, healthy | aucun |
| science | running, healthy ; 275 montages bind en lecture seule | aucun |
| portal | running, healthy ; utilisateur non privilégié, rootfs lecture seule | aucun |
| web | running, healthy ; utilisateur nginx, rootfs lecture seule | `127.0.0.1:18180` |
| idp | running ; pas de healthcheck Compose configuré | `127.0.0.1:18585` |
| migrate | terminé, code 0 | aucun |

Les conteneurs historiques backend/frontend ne sont pas remplacés. Les volumes PostgreSQL et Keycloak locaux sont conservés. Aucun port PostgreSQL/science n'est publié. Le Compose local utilise HTTP et Keycloak `start-dev` : **ne pas exposer sur Internet**.

## Commandes Windows PowerShell

Depuis la racine du dépôt, avec Docker Desktop Linux opérationnel et les artefacts scientifiques existants présents :

```powershell
# Une seule fois sur une nouvelle installation. La configuration actuelle existe déjà :
# ne pas la régénérer au-dessus des volumes persistants.
python deployment/industrial/init-dev.py

docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml build portal web
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml up -d portal web
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml ps -a
```

Ouvrir `http://localhost:18180`. Les identifiants aléatoires de développement sont dans `deployment/industrial/local/accounts.json` ; ne pas les copier dans Git, les rapports ou la conversation. L'administrateur fournisseur et les comptes métier sont distincts. Le générateur refuse volontairement de remplacer `.env`/realm existants. Sur cette installation, reprendre directement aux commandes Compose.

```powershell
# Tests isolés, sans chargement de données MVTec ni poids réels :
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml build tests
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml run --rm tests

# Vérifications en lecture seule :
python deployment/industrial/verify-workspace.py
powershell -NoProfile -ExecutionPolicy Bypass -File deployment/industrial/verify-runtime.ps1

# Parcours réel autorisé sans interruption ni suppression :
node deployment/industrial/browser-qa.mjs
node deployment/industrial/verify-predictions.mjs
node deployment/industrial/history-reconnect-qa.mjs
node deployment/industrial/session-expiry-qa.mjs
```

Le dernier contrôle attend réellement 605 secondes ; il faut le laisser terminer sans trafic sur sa session dédiée. Le scénario navigateur crée de nouvelles inspections et utilise les opérations métier autorisées de partage/révocation ; il ne nettoie pas la base.

Pour le contrôle après redémarrage déjà exécuté : ouvrir un terminal avec `node deployment/industrial/post-restart-qa.mjs`, attendre « Persistence session ready », puis, **uniquement après autorisation explicite**, exécuter dans un second terminal :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deployment/industrial/approved-postgres-restart.ps1 -ApprovedRestart
```

Ce helper effectue les sauvegardes et contrôles documentés, puis exactement :

```powershell
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml restart postgres
```

Le flag du helper ne remplace pas l'autorisation humaine. Le contrôle navigateur séparé ne redémarre rien, ne crée aucune inspection et garde son cookie uniquement en mémoire. Il vérifie ensuite la même session et les mêmes données. La procédure de restauration isolée, non exécutée, est dans [postgres-restart-review.md](postgres-restart-review.md).

Le script navigateur utilise Playwright déjà installé dans `frontend/node_modules` et Chromium correspondant. Il lit les identifiants locaux sans les imprimer et vérifie l'empreinte de l'image MVTec déjà présente `bottle/train/good/002.png`. Les captures et son rapport restent dans le dossier local ignoré. Relancer le scan de logs après son succès.

```powershell
# Régression ciblée effectivement exécutée avec l'environnement scientifique existant :
.venv/Scripts/python.exe -m pytest tests/test_backend_api.py tests/test_compose_deployment.py tests/test_onnx_export.py tests/test_deployment_portability.py -q --tb=short
.venv/Scripts/python.exe scripts/ci/check_api_contract.py
.venv/Scripts/python.exe scripts/prepare_compose.py --check
.venv-mlops/Scripts/python.exe -m pytest scripts/ci/tests -q --tb=short

Set-Location frontend
npm test -- --maxWorkers=2
npm run lint
npm run check:contracts
npm run check:data
npm run build
```

Les nouvelles dépendances Python sont séparées dans `services/portal/requirements*.txt` et l'image dédiée ; aucun changement de `pyproject.toml` ou des environnements scientifiques existants.

## Fichiers proposés à publication pour ce sprint

- `services/portal/` : code BFF, requirements, Dockerfile/allowlist, modèles, migration, tests, configuration pytest/Alembic.
- `deployment/industrial/compose.yml`, `Dockerfile.frontend`, `.env.example`, `01-roles.sh`, `init-dev.py`, `browser-qa.mjs`, `verify-workspace.py`, `verify-runtime.ps1`.
- Helpers de validation : `session-expiry-qa.mjs`, `verify-predictions.mjs`, `history-reconnect-qa.mjs`, `post-restart-qa.mjs`, `approved-postgres-restart.ps1`.
- `frontend/src/portal/`, `frontend/nginx.portal.conf`, `frontend/.dockerignore`.
- Adaptations ciblées : `frontend/src/App.tsx`, `main.tsx`, `api/client.ts`, `studio/history.ts`, `components/StudioPages.tsx`.
- `.gitignore`, `scripts/ci/repository_guard.py`, `scripts/ci/tests/test_policy.py`, `.github/workflows/ci-tests.yml`.
- `docs/industrial/architecture.md`, `security-threat-model.md`, `sprint1-verification.md`, `postgres-restart-review.md`.

**Exclus** : `deployment/industrial/local/` entier (secrets, comptes, realm, sauvegardes initiales, preuves locales, captures), `.venv-portal/`, volumes Docker, MVTec, checkpoints, modèles ONNX et autres artefacts volumineux. La garde de dépôt refuse ces chemins et contenus.

Modifications déjà présentes et laissées intactes, hors liste du sprint : `deployment/reports/onnx-http.json`, `frontend/reports/browser-verification.json`, `reports/experiments/ci_cd_history_audit.json`, `ci_cd_publish_files.txt`, `ci_cd_verification.json`. Leurs empreintes initiales et actuelles correspondent.

Les relevés locaux sont dans `deployment/industrial/local/` : `workspace-verification.json`, `runtime-verification.json`, `browser-verification.json`, `prediction-verification.json`, `history-reconnect-verification.json`, `session-expiry-verification.json`, `restart-verification.json` et `post-restart-verification.json`. Les captures desktop/mobile et les sauvegardes y restent également privées. Aucun de ces fichiers n'est proposé à publication. Les résultats validés sont retranscrits ici sans secrets ni images.

## Limites et décision de revue

La livraison est limitée au **Sprint 1 validé localement**. Les essais réels demandés sont terminés ; aucun Sprint 2, batch, monitoring avancé ou HTTPS public n'a été commencé. Seules les sauvegardes ponctuelles nécessaires au redémarrage approuvé ont été réalisées, sans mise en place d'un dispositif de sauvegarde de production.

Risques restants avant Internet : Keycloak `start-dev`/H2 et HTTP loopback à remplacer par une configuration de production ; TLS, secrets et rotation à déployer ; MFA/politique de comptes à établir ; changements de rôles IdP pris en compte à la prochaine connexion (suspension/révocation locale immédiate disponible), pas de backchannel logout ; politique de conservation des inspections/sessions/audit et capacité en charge à définir ; sauvegardes sensibles non chiffrées de développement et restauration complète non testée ; dépendances transitives à verrouiller/auditer ; revue de sécurité finale nécessaire. L'inactivité signifie ici absence de requêtes : le polling frontend compte comme activité, tandis que la borne absolue de session liée à l'ID token reste applicable.

Les prédictions réelles de cette finalisation portent sur une image bottle et B0/T2 avec les deux moteurs. Elles vérifient l'intégration et ne remplacent pas les jeux de validation scientifique existants. La version n'est **pas déclarée prête pour Internet**. Aucun commit ni push n'a été réalisé.
