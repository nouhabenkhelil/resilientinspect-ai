"""Generate local-only development identities and secrets; never overwrite a setup."""
import json
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[2]
LOCAL = Path(__file__).resolve().parent / "local"


def main():
    LOCAL.mkdir(parents=True, exist_ok=True)
    if (LOCAL / ".env").exists() or (LOCAL / "realm.json").exists():
        raise SystemExit("Existing local configuration preserved; do not regenerate credentials over persistent volumes")
    secret = lambda: secrets.token_urlsafe(36)
    db_owner, db_app, client_secret, session_secret = [secret() for _ in range(4)]
    bootstrap_name, bootstrap_password = "bootstrap-" + secrets.token_hex(5), secret()
    client_id = "resilientinspect-portal"
    realm = {"realm": "resilientinspect", "enabled": True, "registrationAllowed": False,
             "resetPasswordAllowed": False, "loginWithEmailAllowed": False, "sslRequired": "none",
             "bruteForceProtected": True, "failureFactor": 5, "waitIncrementSeconds": 30,
             "accessTokenLifespan": 900, "ssoSessionIdleTimeout": 1800, "ssoSessionMaxLifespan": 3600,
             "roles": {"client": {client_id: [{"name": r} for r in ("admin", "ai_engineer", "operator", "auditor")]}},
             "clients": [{"clientId": client_id, "enabled": True, "protocol": "openid-connect", "publicClient": False,
                          "secret": client_secret, "standardFlowEnabled": True, "implicitFlowEnabled": False,
                          "directAccessGrantsEnabled": False, "serviceAccountsEnabled": False,
                          "redirectUris": ["http://localhost:18180/api/auth/callback"], "webOrigins": [],
                          "attributes": {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": "http://localhost:18180/"},
                          "protocolMappers": [{"name": "business-client-roles", "protocol": "openid-connect",
                            "protocolMapper": "oidc-usermodel-client-role-mapper", "consentRequired": False,
                            "config": {"multivalued": "true", "claim.name": f"resource_access.{client_id}.roles",
                                       "jsonType.label": "String", "id.token.claim": "true", "access.token.claim": "true",
                                       "userinfo.token.claim": "false", "usermodel.clientRoleMapping.clientId": client_id}}]}], "users": []}
    accounts = {}
    for label, role in (("admin", "admin"), ("engineer", "ai_engineer"), ("operator", "operator"), ("operator2", "operator"), ("auditor", "auditor")):
        username, password = label + "-" + secrets.token_hex(3), secret()
        accounts[label] = {"username": username, "password": password, "role": role}
        realm["users"].append({"username": username, "enabled": True, "firstName": "Local", "lastName": role,
                               "email": username + "@example.invalid", "emailVerified": True,
                               "credentials": [{"type": "password", "value": password, "temporary": False}],
                               "clientRoles": {client_id: [role]}})
    values = {"PORTAL_MODE": "development", "PORTAL_ORIGIN": "http://localhost:18180",
              "OIDC_ISSUER": "http://localhost:18585/realms/resilientinspect", "OIDC_INTERNAL_URL": "http://idp:8080/realms/resilientinspect",
              "OIDC_CLIENT_ID": client_id, "OIDC_CLIENT_SECRET": client_secret, "PORTAL_SESSION_SECRET": session_secret,
              "POSTGRES_PASSWORD": db_owner, "PORTAL_DB_PASSWORD": db_app,
              "DATABASE_URL": f"postgresql+psycopg://ri_app:{db_app}@postgres:5432/portal",
              "MIGRATION_DATABASE_URL": f"postgresql+psycopg://ri_migrator:{db_owner}@postgres:5432/portal",
              "TEST_DATABASE_URL": f"postgresql+psycopg://ri_migrator:{db_owner}@postgres:5432/portal_tests",
              "KEYCLOAK_ADMIN_USERNAME": bootstrap_name, "KEYCLOAK_ADMIN_PASSWORD": bootstrap_password}
    (LOCAL / ".env").write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n", encoding="utf-8")
    (LOCAL / "realm.json").write_text(json.dumps(realm, indent=2) + "\n", encoding="utf-8")
    (LOCAL / "accounts.json").write_text(json.dumps({"development_only": True, "accounts": accounts,
             "provider_administrator": {"username": bootstrap_name, "password": bootstrap_password}}, indent=2) + "\n", encoding="utf-8")
    print("Generated development-only configuration in deployment/industrial/local; values not printed. No public registration.")


if __name__ == "__main__": main()
