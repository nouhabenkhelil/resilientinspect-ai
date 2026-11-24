"""Separate batch/worker limits; the worker never needs OIDC/session secrets."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class BatchConfig:
    storage_root: Path = Path('/private/images')
    max_images: int = 50
    max_file_bytes: int = 10 * 1024 * 1024
    max_batch_bytes: int = 100 * 1024 * 1024
    max_pixels: int = 20_000_000
    max_active_per_user: int = 3
    image_retention_hours: int = 24
    result_retention_days: int = 30
    worker_concurrency: int = 1
    max_attempts: int = 3
    retry_seconds: int = 5
    lease_seconds: int = 120
    min_free_bytes: int = 128 * 1024 * 1024

    def __post_init__(self):
        if not (1 <= self.max_images <= 50 and 1 <= self.max_file_bytes <= 10 * 1024 * 1024
                and self.max_file_bytes <= self.max_batch_bytes <= 100 * 1024 * 1024
                and 1 <= self.max_pixels <= 20_000_000):
            raise ValueError('Batch limits exceed the bounded serving contract')
        if not (1 <= self.worker_concurrency <= 2 and 1 <= self.max_attempts <= 3 and 1 <= self.retry_seconds <= 300
                and 120 <= self.lease_seconds <= 600 and 1 <= self.max_active_per_user <= 10):
            raise ValueError('Invalid bounded worker limits')
        if not (1 <= self.image_retention_hours <= 720 and 1 <= self.result_retention_days <= 3650):
            raise ValueError('Invalid retention policy')
        if not self.storage_root.is_absolute():
            raise ValueError('Private batch storage must be an absolute path')

    @classmethod
    def from_env(cls):
        names = {'max_images': 'BATCH_MAX_IMAGES', 'max_file_bytes': 'BATCH_MAX_FILE_BYTES',
                 'max_batch_bytes': 'BATCH_MAX_BYTES', 'max_pixels': 'BATCH_MAX_PIXELS',
                 'max_active_per_user': 'BATCH_MAX_ACTIVE_PER_USER', 'image_retention_hours': 'BATCH_IMAGE_RETENTION_HOURS',
                 'result_retention_days': 'BATCH_RESULT_RETENTION_DAYS', 'worker_concurrency': 'BATCH_WORKER_CONCURRENCY',
                 'max_attempts': 'BATCH_MAX_ATTEMPTS', 'retry_seconds': 'BATCH_RETRY_SECONDS', 'lease_seconds': 'BATCH_LEASE_SECONDS'}
        values = {field: int(os.environ[name]) for field, name in names.items() if name in os.environ}
        return cls(storage_root=Path(os.getenv('BATCH_STORAGE_ROOT', '/private/images')), **values)


@dataclass(frozen=True)
class WorkerConfig:
    database_url: str = field(repr=False)
    scientific_url: str = 'http://science:8000'
    inference_timeout: int = 90
    max_inflight: int = 2

    def __post_init__(self):
        u = urlsplit(self.scientific_url)
        if (not self.database_url.startswith('postgresql+psycopg://') or u.scheme not in {'http', 'https'}
                or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in {'', '/'}):
            raise ValueError('Fixed internal science URL and PostgreSQL required')

    @classmethod
    def from_env(cls):
        return cls(database_url=os.environ['DATABASE_URL'], scientific_url=os.getenv('SCIENTIFIC_URL', 'http://science:8000'))
