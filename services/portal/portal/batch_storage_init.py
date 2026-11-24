"""Initialize only the new private image volume; existing ownership is preserved."""
import os
from pathlib import Path


def main():
    root = Path('/private')
    if root.is_symlink(): raise RuntimeError('Private volume must not be a symlink')
    owner = root.stat().st_uid
    if owner == 10002:
        return  # Already initialized; root deliberately lacks permission to traverse private images.
    if owner != 0: raise RuntimeError('Unexpected private volume owner')
    images = root / 'images'
    images.mkdir(exist_ok=True)
    os.chmod(images, 0o700)
    os.chown(images, 10002, 10002)
    os.chmod(root, 0o700)
    os.chown(root, 10002, 10002)


if __name__ == '__main__': main()
