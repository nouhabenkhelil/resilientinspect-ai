# Sprint 1 — audit et modèle de menace

Périmètre : nouvelle couche industrielle locale, fournisseur OIDC, sessions, autorisations par inspection, PostgreSQL et proxy. Les résultats scientifiques et preuves antérieures ne sont pas recalculés. Ce document est une revue d'implémentation, pas une certification ni un audit externe.

Actifs : identités provisionnées, sessions opaques, métadonnées d'inspection, images transitoires, journal d'audit et références scientifiques SHA256. Frontières : navigateur/proxy, BFF/IdP, BFF/SQL et BFF/science. L'hôte Windows et l'administrateur Docker sont de confiance dans ce sprint. Une personne ayant accès à l'hôte ou au socket Docker peut lire les secrets et volumes locaux.

| Menace constatée ou anticipée | Contrôle livré | Vérification et limite |
|---|---|---|
| Démonstrateur sans authentification métier | Portail indépendant, aucune option auth-off | Configuration production refusée si incomplète ; démo historique conservée sur loopback |
| Vol/rejeu de code, login CSRF, mélange d'issuer | Code+PKCE S256, nonce, state et cookie de liaison, consommation unique, issuer fixe | Fixtures RSA et parcours Keycloak réel validés ; paramètres Code/S256/state/nonce observés |
| Token forgé ou claims incohérents | JWKS fournisseur, RS256 uniquement, audience/issuer/nonce/iat/exp et rôle unique | Tests négatifs de claims, signature et algorithme |
| Token volé dans JS ou SQL | Cookie HttpOnly, identifiant opaque, HMAC SQL ; pas de bearer/refresh persistant | Tests session/CSRF ; cookie invisible à JS et aucune clé sensible dans les stockages navigateur réels |
| Session expirée, révoquée, compte suspendu | Contrôle SQL à chaque requête, bornes absolue/inactivité, révocation admin et logout | Révocation/logout réels et expiration naturelle 605 s validés ; suspension couverte par fixtures antérieures |
| CSRF | Origine exacte et jeton dérivé du cookie, en mémoire seulement | Tests mutation sans jeton, jeton faux et origine hostile |
| IDOR et élévation de rôle | Filtre SQL partagé listes/détails ; 404 hors périmètre ; grants admin explicites | Tests quatre rôles, propriétaire différent, partage et refus auditor en écriture |
| Réponse historique d'un ancien compte | Invalidation de génération lors de logout/changement d'identité | Test React de réponse tardive ; pas d'inspection industrielle en localStorage |
| Injection SQL ou paramètres de tri | SQLAlchemy paramétré, enums, pagination bornée | Tests filtres invalides ; pas de SQL client accepté |
| SSRF et accès direct à science | URL fixe, aucun paramètre URL accepté, redirects désactivés, réseau Docker privé | Tests destination simulée ; Compose science/SQL sans ports publiés |
| Fichier renommé, décompression abusive, surcharge | MIME réel Pillow, extension cohérente, dimensions/taille, corps proxy/BFF, timeouts | Tests formats, contenu, dimensions, taille et formulaire inattendu |
| Saturation CPU et quotas contournés | Compteurs SQL atomiques, baux globaux/par utilisateur, proxy limité | Test concurrent de quota et capacité ; dimensionnement en charge réelle restant |
| Fuite de secrets dans erreurs/logs | Réponses fixes, pas d'exception brute, proxy sans query, audit UUID uniquement | Scan réel des secrets configurés/JWT ; 5 valeurs dynamiques Code/state/flow/session/CSRF contrôlées sans correspondance |
| Altération d'audit et provenance | Permissions SQL append-only audit/versions ; bindings SHA reçus ; science inchangée | Tests privilèges SQL ; admission scientifique SHA256 toujours active |
| Images persistées involontairement | Aucune colonne image/base64 ; données temporaires seulement, empreinte image désactivée | Tests inspection SQL ; politique de rétention production à définir |
| Secrets ou données dans Git/images | Dossier local ignoré et garde CI, contextes Docker par allowlist | Garde dépôt exécutée ; identifiants générés sans affichage |
| Rupture de l'environnement historique | Projet/volumes/ports distincts ; aucun changement au Compose historique | Empreintes sources/proofs et états des services vérifiés sans réexport |

Les essais réels du Sprint 1 sont terminés, y compris la conservation de 11 inspections et d'une session après un restart PostgreSQL explicitement autorisé. Les archives de développement sont lisibles ; aucune restauration complète n'a été effectuée. Limites avant production : revue externe ; TLS et gestion de secrets ; IdP de production avec MFA/politique comptes ; renouvellement/rotation des secrets et coupure des sessions lors d'un changement IdP ; politique de conservation et droit d'accès aux données ; rétention/export de l'audit ; sauvegardes protégées et restauration réellement testée ; dimensionnement et audit/verrouillage des dépendances transitives. La protection de l'interface ne remplace aucune autorisation serveur.

Le fournisseur doit émettre les rôles dans `resource_access.<OIDC_CLIENT_ID>.roles` de l'ID token, un seul parmi les quatre rôles. Le provisioning et le retrait d'accès IdP sont administratifs. Le BFF ne synchronise pas en continu les changements IdP : utiliser suspension/révocation locale pour un retrait immédiat. La déconnexion fournisseur peut demander confirmation et n'est pas du backchannel logout.

Références de conception : [OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html), [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html), [OWASP CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html), [Keycloak containers](https://www.keycloak.org/server/containers).
