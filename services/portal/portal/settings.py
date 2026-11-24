"""Fail-closed configuration; development relaxes transport only, never authentication."""
from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    mode: str = "production"
    origin: str = ""
    issuer: str = ""
    oidc_internal: str = ""
    client_id: str = ""
    client_secret: str = field(default="", repr=False)
    session_secret: str = field(default="", repr=False)
    database_url: str = field(default="", repr=False)
    scientific_url: str = "http://science:8000"
    session_seconds: int = 1800
    idle_seconds: int = 600
    prediction_per_minute: int = 10
    prediction_per_hour: int = 60
    max_inflight: int = 2
    inference_timeout: int = 90
    max_file_bytes: int = 10 * 1024 * 1024
    max_pixels: int = 20_000_000
    store_image_hash: bool = False

    def __post_init__(self):
        if self.mode not in {"development", "production"}:
            raise ValueError("PORTAL_MODE must be development or production; no authentication-off mode")
        if not all((self.origin, self.issuer, self.client_id, self.client_secret, self.database_url)) or len(self.session_secret) < 43:
            raise ValueError("Mandatory OIDC/database/session configuration missing")
        if len(self.client_secret) < 20 or not self.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("Strong client secret and PostgreSQL psycopg URL required")
        for value in (self.origin, self.issuer, self.oidc_internal or self.issuer, self.scientific_url):
            u = urlsplit(value)
            if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ValueError("Unsafe fixed service URL")
        public = urlsplit(self.origin)
        if public.path not in {"", "/"}:
            raise ValueError("PORTAL_ORIGIN must be an origin without a path")
        if self.origin.endswith("/") or self.issuer.endswith("/") or self.scientific_url.endswith("/"):
            raise ValueError("Configured URLs must not have trailing slashes")
        if self.mode == "production" and any(urlsplit(v).scheme != "https" for v in (self.origin, self.issuer)):
            raise ValueError("Production requires HTTPS public origin and OIDC issuer")
        if self.mode == "development" and public.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Development origin must be loopback")
        if not (60 <= self.session_seconds <= 28800 and 30 <= self.idle_seconds <= self.session_seconds):
            raise ValueError("Invalid bounded session lifetime")
        if not (1 <= self.max_inflight <= 4 and 1 <= self.inference_timeout <= 120):
            raise ValueError("Invalid resource limit")

    @property
    def cookie_name(self):
        return "__Host-ri_portal_session" if self.mode == "production" else "ri_portal_session"

    @property
    def secure_cookie(self):
        return self.mode == "production"

    @classmethod
    def from_env(cls):
        return cls(mode=os.getenv("PORTAL_MODE", "production"), origin=os.getenv("PORTAL_ORIGIN", ""),
                   issuer=os.getenv("OIDC_ISSUER", ""), oidc_internal=os.getenv("OIDC_INTERNAL_URL", ""),
                   client_id=os.getenv("OIDC_CLIENT_ID", ""), client_secret=os.getenv("OIDC_CLIENT_SECRET", ""),
                   session_secret=os.getenv("PORTAL_SESSION_SECRET", ""), database_url=os.getenv("DATABASE_URL", ""),
                   scientific_url=os.getenv("SCIENTIFIC_URL", "http://science:8000"),
                   store_image_hash=os.getenv("STORE_IMAGE_HASH", "false").lower() == "true")
