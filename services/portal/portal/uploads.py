"""Bounded content validation before forwarding original bytes unchanged."""
from io import BytesIO
from pathlib import PurePath
import warnings

from PIL import Image, UnidentifiedImageError

from .security import PublicError


def validate_image(content, filename, settings):
    expected = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}.get(PurePath(filename).suffix.lower())
    if expected is None:
        raise PublicError(415, "unsupported_extension", "Utilisez une image PNG ou JPEG.")
    if not content or len(content) > settings.max_file_bytes:
        raise PublicError(413 if content else 400, "invalid_upload", "Image vide ou trop volumineuse.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content), formats=["PNG", "JPEG"]) as image:
                if image.format != expected or getattr(image, "n_frames", 1) != 1:
                    raise PublicError(415, "format_mismatch", "Le contenu et l’extension de l’image ne correspondent pas.")
                if image.width * image.height > settings.max_pixels:
                    raise PublicError(413, "image_too_large", "Les dimensions de l’image dépassent la limite.")
                image.verify()
            with Image.open(BytesIO(content), formats=["PNG", "JPEG"]) as image:
                image.load()
    except PublicError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise PublicError(413, "image_too_large", "Les dimensions de l’image dépassent la limite.") from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise PublicError(400, "invalid_image", "Cette image est illisible ou corrompue.") from None
    return "image/png" if expected == "PNG" else "image/jpeg"
