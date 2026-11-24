# Sprint 1 — procédure soumise à autorisation

Ce document décrit la procédure présentée avant autorisation. **L'utilisateur a ensuite explicitement autorisé les sauvegardes et le redémarrage ciblé**, exécutés le 24 novembre 2026 après le test d'expiration naturelle. Le parcours navigateur initial a été exécuté sans `--restart-postgres`. Aucune restauration n'a été exécutée ni autorisée.

Résultat réel : les deux dumps et les rôles sont sauvegardés dans `deployment/industrial/local/backups/20261124-151517/`, archives custom lisibles, même volume et snapshot métier strictement identique après le seul restart PostgreSQL. Les 11 inspections et la session navigateur de contrôle sont conservées. Détails et limites : [sprint1-verification.md](sprint1-verification.md). Toute répétition de cette interruption nécessite une nouvelle autorisation ; le flag du helper n'est pas une preuve d'autorisation à lui seul.

## Actions inspectées

Dans `browser-qa.mjs`, l'option `--restart-postgres` appelle exactement :

```powershell
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml restart postgres
```

Le script attend ensuite une réponse HTTP 200 sur le détail d'une inspection et compare sa version, pendant au plus 30 secondes. Il n'exécute ni suppression de volume, ni `down`, ni réinitialisation de Keycloak. Cependant, relancer ce script complet produirait à nouveau les inspections et les mutations d'autorisation du scénario. Pour éviter cette répétition, la validation après redémarrage devra utiliser un contrôle de persistance séparé portant sur les inspections déjà enregistrées.

## Périmètre réel inspecté

- Projet Compose : `resilientinspect-industrial`.
- Conteneur ciblé : `resilientinspect-industrial-postgres-1` uniquement.
- Volume Docker existant : **`resilientinspect-industrial_postgres-data`**, monté en écriture sur `/var/lib/postgresql/data`.
- Initialisation montée en lecture seule : `deployment/industrial/01-roles.sh`. Elle ne se réexécute pas sur un cluster existant lors d'un simple restart.
- Bases dans ce cluster : `portal` et `portal_tests` ; comptes/permissions PostgreSQL et WAL également sur le volume. Le fournisseur Keycloak utilise un autre volume et sa propre base locale H2 ; il n'est pas ciblé.
- Relevé en lecture seule après les essais réels : révision `d1c1799c7017`, 5 profils, **11 inspections (10 completed, 1 failed)**, 2 versions de modèle, aucun bail de calcul actif. Les compteurs de sessions/audit continuent naturellement d'évoluer pendant les tests.
- Science, portail, proxy V3, démonstrateur V2 et Oracle ne figurent pas dans la commande. Leurs conteneurs ne sont pas redémarrés.

Conséquence attendue : interruption brève de toutes les connexions à **ce PostgreSQL**, donc indisponibilité temporaire de l'authentification, de l'historique et des nouvelles inspections V3. Les sessions/inspections doivent rester dans le même volume ; les pools SQL doivent se reconnecter. Les connexions des tests utilisant `portal_tests` seraient aussi interrompues. Aucun test SQL ne doit être en cours et aucun calcul ne doit être actif au lancement. V2 utilise son backend scientifique distinct ; Oracle n'utilise pas ce PostgreSQL.

Un restart ne supprime normalement aucune donnée persistante, mais il interrompt des connexions/transactions en cours. L'autorisation demandée couvre cette interruption précise, précédée des sauvegardes logiques ci-dessous. Elle ne couvre aucune restauration, suppression ou réinitialisation.

## Sauvegarde logique préalable proposée

Depuis la racine du dépôt, après autorisation. Les dumps comprennent profils, sessions, audit, résultats et permissions ; `globals.sql` peut contenir des empreintes de mots de passe. Ces fichiers sont sensibles, restent dans `deployment/industrial/local/backups/` ignoré par Git et ne doivent pas être affichés, joints à un rapport ou publiés. Il ne s'agit pas d'un dispositif de sauvegarde de production.

Le format custom est écrit directement dans le conteneur puis copié en binaire avec `docker cp` : **aucune redirection PowerShell de flux binaire**.

```powershell
$dc = @('compose', '--env-file', 'deployment/industrial/local/.env', '-f', 'deployment/industrial/compose.yml')
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$localRoot = (Resolve-Path 'deployment/industrial/local').Path
$backupDir = Join-Path $localRoot "backups/$stamp"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$containerId = (& docker @dc ps -q postgres | Out-String).Trim()
if ($containerId -notmatch '^[a-f0-9]{12,64}$') { throw 'Unexpected PostgreSQL container identity' }

foreach ($databaseName in @('portal', 'portal_tests')) {
    $archive = "/tmp/ri-$stamp-$databaseName.dump"
    & docker @dc exec -T postgres pg_dump -U ri_migrator -d $databaseName -Fc -f $archive
    if ($LASTEXITCODE -ne 0) { throw 'Backup failed; do not restart' }
    & docker cp "${containerId}:$archive" (Join-Path $backupDir "$databaseName.dump")
    if ($LASTEXITCODE -ne 0) { throw 'Copy failed; do not restart' }
    & docker @dc exec -T postgres pg_restore --list $archive | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Archive unreadable; do not restart' }
}
$globals = "/tmp/ri-$stamp-globals.sql"
& docker @dc exec -T postgres pg_dumpall -U ri_migrator --globals-only --file $globals
if ($LASTEXITCODE -ne 0) { throw 'Global-role backup failed; do not restart' }
& docker cp "${containerId}:$globals" (Join-Path $backupDir 'globals.sql')
if ($LASTEXITCODE -ne 0) { throw 'Global-role copy failed; do not restart' }
Get-ChildItem -LiteralPath $backupDir -File | Get-FileHash -Algorithm SHA256
```

`pg_dump` prend un snapshot cohérent de chaque base sans réinitialisation. Les deux snapshots ne sont pas simultanés ; ces bases métier/test sont indépendantes. `pg_restore --list` contrôle la lisibilité de l'archive, **pas une restauration complète**. Les fichiers temporaires du conteneur ne sont pas supprimés automatiquement. Les copies hôte restent disponibles même si le conteneur est remplacé.

## Restauration proposée, autorisation distincte requise

Ne pas restaurer automatiquement dans `portal` : cela pourrait écraser des données plus récentes. En cas de besoin, conserver le volume courant et restaurer d'abord dans une **nouvelle base isolée** dont l'absence est vérifiée. Les rôles `ri_migrator`/`ri_app` existent sur ce cluster ; le dump custom conserve propriétaires et permissions. Sur un autre cluster, faire revoir les rôles et `globals.sql` avant toute application ; ne jamais imprimer son contenu.

Exemple de procédure isolée à soumettre séparément, avec le chemin de sauvegarde réel et un nom de base neuf :

```powershell
# NON EXÉCUTÉ — création/restauration nécessitent une autorisation distincte.
$restoreDatabase = 'portal_restorecheck_YYYYMMDD_HHMMSS'
docker cp 'deployment/industrial/local/backups/<horodatage>/portal.dump' 'resilientinspect-industrial-postgres-1:/tmp/portal-restorecheck.dump'
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml exec -T postgres createdb -U ri_migrator --template=template0 $restoreDatabase
docker compose --env-file deployment/industrial/local/.env -f deployment/industrial/compose.yml exec -T postgres pg_restore -U ri_migrator --exit-on-error --single-transaction --dbname $restoreDatabase /tmp/portal-restorecheck.dump
```

Après restauration isolée : comparer révision Alembic, nombres/UUID d'inspections, scores/seuils/décisions/SHA256, propriétaires, sessions et permissions SQL. Ne changer la connexion du portail qu'après revue de ces résultats et autorisation distincte. Aucun `DROP DATABASE`, `--clean`, effacement de volume ou réinitialisation Keycloak n'est proposé.

## Contrôle après restart proposé

1. Sauvegardes terminées et archives lisibles ; relever de nouveau les inspections de référence et la révision en lecture seule.
2. Après autorisation explicite, exécuter **uniquement** la commande `restart postgres` présentée plus haut.
3. Attendre `pg_isready`, puis vérifier l'état PostgreSQL et les endpoints authentifiés V3 avec une session encore valide ou une reconnexion OIDC.
4. Comparer les 11 inspections déjà présentes, leurs UUID/résultats/SHA et leurs propriétaires. Ne pas recréer des inspections pour simuler la persistance.
5. Relever HTTP 200 de V2:18080 et V3:18180, admissions 15/14, absence de ports SQL/science et logs assainis. Consigner le résultat réel, sans affirmer de restauration tant qu'elle n'a pas été testée.
