# Sprint 3 — périmètre à autoriser

Le code d'observabilité et de sauvegarde est préparé avant déploiement. Le projet scientifique V2 et les volumes existants ne sont pas remplacés, supprimés ni réinitialisés.

## Intervention proposée sur V3

1. Appliquer une migration additive `service_heartbeats` et provisionner un compte observateur SQL en lecture seule.
2. Renouveler uniquement les images/services V3 portal, worker et web pour activer logs, métriques et System Monitor. Quelques secondes de disponibilité réduite sont possibles ; les baux persistants protègent les tâches.
3. Pour une sauvegarde cohérente, arrêter temporairement **web, portal, worker et idp** du projet `resilientinspect-industrial`. Le worker reçoit SIGTERM et peut terminer son item pendant au plus 110 s. **PostgreSQL et le backend scientifique restent en marche**, tout comme V2:18080 et Oracle.
4. Pendant cette fenêtre : dump logique de `portal`, copie en lecture seule des volumes `resilientinspect-industrial_idp-data` (H2 arrêté) et `resilientinspect-industrial_batch-images`, et copie des configurations privées indispensables.
5. Redémarrer tous les services qui étaient actifs avant l'opération, y compris en cas d'erreur. La fenêtre visée est de quelques dizaines de secondes à environ trois minutes, selon un calcul déjà en cours et le redémarrage de Keycloak. La durée réelle sera mesurée.

Commande préparée :

```powershell
.venv-ops/Scripts/python.exe deployment/operations/backup.py core --approved-maintenance
```

La sauvegarde est chiffrée AES-256-GCM **dès sa création**, avec manifeste et SHA256. Destination privée hors dépôt : `C:\Users\nouhe\ResilientInspectBackups`. Clé distincte : `C:\Users\nouhe\.resilientinspect-secrets\backup.key`. Aucun secret ne doit être affiché ni placé dans une archive publique. Les fichiers temporaires en clair restent dans un sous-dossier privé nouvellement créé puis sont nettoyés ; aucune suppression de volume n'est effectuée.

La copie est locale, sur la même machine : elle ne protège pas contre sa perte physique. Une copie hors machine des archives chiffrées et la conservation séparée de la clé restent à organiser ; aucun transfert externe ne sera effectué automatiquement.

## Automatisation proposée

Après accord explicite pour ces interruptions récurrentes : un processus Windows masqué vérifie chaque minute l'échéance d'une sauvegarde core **toutes les 24 h** et d'une sauvegarde MLOps **tous les 7 jours**. Conservation initiale : 7 core et 4 MLOps, rotation limitée aux archives créées par cet outil. Les échéances sont configurables dans le fichier privé `backup-config.json`. La copie MLflow/DVC est indépendante et ne nécessite pas d'arrêt V3 ; ses fichiers sources ne sont pas modifiés. Le daemon fonctionne tant que le PC et la session qui l'héberge sont actifs ; ce n'est pas un service serveur garanti 24/7.

## Restauration et pannes isolées

La restauration sera faite dans un **nouveau projet Docker `resilientinspect-recovery-*`**, avec de nouveaux volumes et des ports loopback distincts. Elle ne ciblera jamais les bases actuellement utilisées. Les rôles/clients et URLs seront adaptés seulement dans la copie. Les snapshots métier et les SHA256 des images seront comparés avant les essais. Les tests de crash worker, d'arrêt PostgreSQL et de déclenchement/résolution des alertes affecteront uniquement cet environnement isolé.

Aucune restauration en place, suppression de volume, réinitialisation de PostgreSQL/Keycloak existant ou exposition Internet ne fait partie de l'autorisation demandée.

## Extension autorisée pendant la validation

Le 24 novembre 2026, après des erreurs HTTP 500 de l'API Docker, l'utilisateur a autorisé explicitement un redémarrage global **si nécessaire**, avec interruption temporaire de tous les conteneurs (V3/PostgreSQL/Keycloak, V2 et autres projets actifs), sans suppression de volume. Commande inspectée : `docker desktop restart --timeout 120`. Cet accord ponctuel n'autorise pas des redémarrages Docker globaux récurrents.

L'environnement WSL est limité à 4 Go de RAM et 2 Go de swap. Les validations de restauration doivent plafonner Keycloak de la copie, l'arrêter après les essais OIDC et construire les images séquentiellement. Les services tiers restent sous le contrôle de l'utilisateur.
