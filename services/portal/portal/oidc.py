"""OIDC Authorization Code/PKCE, using Authlib's signed CodeIDToken validation."""
import base64
import hashlib
from urllib.parse import urlsplit
from urllib.parse import urlencode

from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.core import CodeIDToken
from joserfc import jwt
from joserfc.jwk import KeySet
from cryptography.fernet import Fernet
import httpx2 as httpx

from .security import PublicError


class OIDC:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport  # Dependency injection for isolated tests, never an environment auth bypass.
        self.cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.session_secret.encode()).digest()))
        self._metadata = None

    def internal(self, url):
        issuer = self.settings.issuer
        if not url.startswith(issuer + "/") or urlsplit(url).fragment or urlsplit(url).query:
            raise PublicError(503, "oidc_configuration", "Le fournisseur de connexion est indisponible.")
        return (self.settings.oidc_internal or issuer) + url[len(issuer):]

    async def metadata(self):
        if self._metadata is None:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False, transport=self.transport, trust_env=False) as client:
                response = await client.get((self.settings.oidc_internal or self.settings.issuer) + "/.well-known/openid-configuration")
                response.raise_for_status()
                if len(response.content) > 128 * 1024:
                    raise ValueError("OIDC metadata too large")
                meta = response.json()
            if meta.get("issuer") != self.settings.issuer or "RS256" not in meta.get("id_token_signing_alg_values_supported", []):
                raise ValueError("OIDC issuer or signing algorithm mismatch")
            for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                self.internal(meta[field])
            if "S256" not in meta.get("code_challenge_methods_supported", []):
                raise ValueError("PKCE S256 required")
            self._metadata = meta
        return self._metadata

    def client(self):
        return AsyncOAuth2Client(self.settings.client_id, self.settings.client_secret,
                                redirect_uri=self.settings.origin + "/api/auth/callback", scope="openid profile email",
                                code_challenge_method="S256", token_endpoint_auth_method="client_secret_basic",
                                timeout=10, follow_redirects=False, transport=self.transport, trust_env=False)

    async def authorization(self, state, nonce, verifier):
        metadata = await self.metadata()
        async with self.client() as client:
            url, _ = client.create_authorization_url(metadata["authorization_endpoint"], state=state,
                                                     nonce=nonce, code_verifier=verifier)
        return url

    async def identity(self, code, nonce, verifier):
        meta = await self.metadata()
        async with self.client() as client:
            token = await client.fetch_token(self.internal(meta["token_endpoint"]), code=code, code_verifier=verifier,
                                             grant_type="authorization_code")
        if not isinstance(token.get("id_token"), str) or len(token["id_token"]) > 32 * 1024:
            raise ValueError("Signed OIDC ID token required")
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, transport=self.transport, trust_env=False) as client:
            response = await client.get(self.internal(meta["jwks_uri"]))
            response.raise_for_status()
            if len(response.content) > 128 * 1024:
                raise ValueError("OIDC key set too large")
            keys = response.json()
        verified = jwt.decode(token["id_token"], KeySet.import_key_set(keys), algorithms=["RS256"])
        claims = CodeIDToken(verified.claims, verified.header,
                                options={"iss": {"essential": True, "value": self.settings.issuer},
                                                "sub": {"essential": True}, "exp": {"essential": True},
                                                "iat": {"essential": True}, "aud": {"essential": True}},
                                params={"client_id": self.settings.client_id, "nonce": nonce,
                                               "access_token": token.get("access_token")})
        claims.validate(leeway=5)
        audience = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
        if self.settings.client_id not in audience or not isinstance(claims["sub"], str) or not (1 <= len(claims["sub"]) <= 255):
            raise ValueError("OIDC audience or subject mismatch")
        roles = claims.get("resource_access", {}).get(self.settings.client_id, {}).get("roles", [])
        allowed = set(roles) & {"admin", "ai_engineer", "operator", "auditor"}
        # One explicit business role avoids ambiguous combined privileges.
        if len(allowed) != 1:
            raise PublicError(403, "account_not_provisioned", "Votre accès doit être provisionné par un administrateur.")
        # Tokens are discarded, never persisted or returned to React.
        return {"subject": claims["sub"], "name": str(claims.get("name") or claims.get("preferred_username") or "Utilisateur")[:160],
                "email": str(claims["email"])[:255] if claims.get("email_verified") is True and claims.get("email") else None,
                "role": allowed.pop(), "expires": claims["exp"]}

    async def logout_url(self):
        metadata = await self.metadata()
        url = metadata.get("end_session_endpoint")
        if not url:
            return self.settings.origin + "/"
        self.internal(url)  # Validate origin/path; browser uses the public endpoint.
        return url + "?" + urlencode({"client_id": self.settings.client_id,
                                       "post_logout_redirect_uri": self.settings.origin + "/"})
