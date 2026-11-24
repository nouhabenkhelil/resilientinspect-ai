"""Private UUID-only storage. User filenames are labels, never destinations."""
import hashlib
import os
from pathlib import Path
import shutil
import unicodedata
from uuid import UUID, uuid4
from .security import PublicError


def clean_filename(value):
    name = unicodedata.normalize('NFKC', value or '').replace('\\', '/').split('/')[-1]
    name = ''.join(c for c in name if not unicodedata.category(c).startswith('C')).strip().lstrip('.')[:160]
    if not name:
        raise PublicError(415, 'invalid_filename', 'Nom de fichier invalide.')
    return name


class PrivateStorage:
    def __init__(self, config):
        self.root = Path(config.storage_root)
        self.min_free = config.min_free_bytes

    def path(self, ref):
        return self.root / UUID(str(ref)).hex

    def ready(self):
        return self.root.is_dir() and not self.root.is_symlink() and os.access(self.root, os.W_OK)

    def write(self, content):
        if not self.ready():
            raise PublicError(503, 'storage_unavailable')
        if shutil.disk_usage(self.root).free < len(content) + self.min_free:
            raise PublicError(507, 'storage_capacity', 'Le stockage privé est temporairement saturé.')
        ref = uuid4()
        descriptor = os.open(self.path(ref), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if hasattr(os, 'O_DIRECTORY'):
                directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try: os.fsync(directory)
                finally: os.close(directory)
        except BaseException:
            self.delete(ref)
            raise
        return ref

    def read(self, ref, expected_sha, max_bytes):
        try:
            descriptor = os.open(self.path(ref), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(descriptor, 'rb') as stream:
                data = stream.read(max_bytes + 1)
        except (OSError, ValueError):
            raise PublicError(410, 'image_unavailable', 'Cette image privée n’est plus disponible.') from None
        if len(data) > max_bytes or hashlib.sha256(data).hexdigest() != expected_sha:
            raise PublicError(409, 'image_integrity_failed', 'L’intégrité du fichier privé ne peut pas être confirmée.')
        return data

    def delete(self, ref):
        try:
            self.path(ref).unlink()
        except FileNotFoundError:
            pass
