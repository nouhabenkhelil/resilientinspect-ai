# Sauvegarde locale Sprint 3

## Périmètre et cycles

L'utilisateur a approuvé les interruptions V3 ponctuelles et leur répétition quotidienne. `backup.py core --approved-maintenance` arrête uniquement les conteneurs existants web, portal, worker et idp qui étaient actifs ; PostgreSQL et le moteur scientifique restent actifs. Le dump logique de `portal`, H2 Keycloak arrêté, les images privées et la configuration correspondent alors à la même fenêtre sans écritures applicatives. La reprise cible les conteneurs exacts, sans relancer des dépendances de migration. Le worker termine son item sur SIGTERM avec une grâce de 110 secondes. Le démarrage ne réinitialise aucun volume.

Core : échéance 24 heures, sept archives conservées. MLOps : échéance sept jours, quatre archives conservées. SQLite MLflow est copié par l'API backup en lecture seule ; les artefacts et le remote DVC sont inventoriés par SHA256 avant/après copie, sans commande d'écriture DVC/MLflow. Les deux cycles ont des archives indépendantes. Un verrou Windows exclut deux acquisitions simultanées.

## Confidentialité et intégrité

Destination : `C:\Users\nouhe\ResilientInspectBackups`, hors dépôt. Clé AES-256 distincte : `C:\Users\nouhe\.resilientinspect-secrets\backup.key`. Les deux répertoires utilisent une ACL explicite pour le propriétaire, SYSTEM et les administrateurs. Les archives sont chiffrées en AES-GCM avec nonce aléatoire et authentification du format. SHA256 du ciphertext dans le manifeste extérieur ; inventaire SHA256 des fichiers dans le manifeste intérieur chiffré. Les données métier, comptes et secrets restent dans l'archive chiffrée.

Le répertoire temporaire en clair est privé et propre à chaque acquisition. Le programme refuse les liens, chemins absolus et traversées à l'extraction. Aucune extraction avant vérification GCM. La rotation vérifie nom, paire archive/manifeste et SHA256 ; elle ne cible ni volumes Docker ni autres fichiers. Un incident de nettoyage Windows a laissé un fichier SQLite dans `.staging` ; sa suppression a été refusée par le contrôle automatique. Il reste privé, sans contournement du refus. Les connexions SQLite sont maintenant fermées explicitement.

## Automatisation et exploitation PowerShell

```powershell
.venv-ops/Scripts/python.exe -m pip install -r deployment/operations/requirements.txt
.venv-ops/Scripts/python.exe deployment/operations/init.py
./deployment/operations/start-backups.ps1
Get-Content deployment/industrial/local/observability/daemon.json
Get-Content C:\Users\nouhe\ResilientInspectBackups\operations.jsonl -Tail 10
```

Le daemon masqué vérifie chaque minute les échéances configurées dans le fichier privé `backup-config.json`. Il exige l'accord de maintenance et s'appuie sur les archives achevées, pas sur les tentatives échouées. `start-backups.ps1` évite de lancer une seconde instance déjà identifiée. Il ne s'agit pas d'un service Windows garanti : PC arrêté, session fermée ou daemon arrêté suspendent les sauvegardes ; relancer cette commande après connexion. Les erreurs sont enregistrées hors dépôt, sans secrets. Le processus doit être redémarré après mise à jour de son code.

## Restauration et objectifs

```powershell
.venv-ops/Scripts/python.exe deployment/operations/verify_backup.py C:\Users\nouhe\ResilientInspectBackups\core-<identifiant>.ri3
.venv-ops/Scripts/python.exe deployment/operations/recovery.py C:\Users\nouhe\ResilientInspectBackups\core-<identifiant>.ri3
node deployment/operations/operations-qa.mjs --recovery
```

Le script crée un nouveau projet `resilientinspect-recovery-*`, des volumes neufs et des ports loopback 18680/18685. Il refuse une base de destination peuplée. Les données sont comparées avant adaptation des seules URLs OIDC de la copie ; les UUID et propriétaires restent identiques. Les fichiers privés sont comparés à l'inventaire SHA256 PostgreSQL. Le worker est démarré après cette comparaison, par la validation de reprise. Les volumes de restauration sont conservés, sans `down -v`. Une reprise `--finish-existing-project` termine la configuration d'un clone déjà restauré et revérifie les données ; elle ne réimporte pas sa base.

RPO **cible**, conditionnel au fonctionnement du daemon : au plus 24 h core et sept jours MLOps. Ce n'est pas une garantie constatée sur plusieurs jours. RTO mesuré et incidents de validation : voir `sprint3-verification.md` et `restore-report.md`. La copie partage le PC et son disque : **elle ne protège pas contre leur perte physique**. La copie hors machine des seules archives chiffrées et l'escrow séparé de la clé restent à organiser ; aucun transfert externe ni restauration en place n'est autorisé ici.
