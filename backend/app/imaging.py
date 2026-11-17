"""Validation des uploads et rendu dans les coordonnees du letterbox."""

import base64
from io import BytesIO
from pathlib import Path
import warnings

from fastapi import UploadFile
import numpy as np
from PIL import Image, UnidentifiedImageError

from resilientinspect.data.dataset import letterbox_pair

from .config import Settings
from .errors import APIError
from .schemas import Visualization


FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}


def decode_upload(file: UploadFile, settings: Settings) -> dict:
    expected = FORMATS.get(Path(file.filename or "").suffix.lower())
    if expected is None:
        raise APIError(415, "unsupported_extension", "Extensions acceptees : .png, .jpg, .jpeg.")
    content = file.file.read(settings.max_file_bytes + 1)
    if len(content) > settings.max_file_bytes:
        raise APIError(413, "file_too_large", "Le fichier depasse la taille autorisee.")
    if not content:
        raise APIError(400, "invalid_image", "Le fichier image est vide.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content), formats=["PNG", "JPEG"]) as image:
                if image.format != expected:
                    raise APIError(415, "format_mismatch", "Le format de l'image ne correspond pas a son extension.")
                if image.width * image.height > settings.max_image_pixels:
                    raise APIError(413, "image_too_large", "Le nombre de pixels depasse la limite autorisee.")
                if getattr(image, "n_frames", 1) != 1:
                    raise APIError(415, "animated_image", "Une image fixe est requise.")
                image.verify()
            with Image.open(BytesIO(content), formats=["PNG", "JPEG"]) as image:
                image.load()
                rgb = image.convert("RGB")
                return letterbox_pair(rgb, Image.new("L", rgb.size, 0), (256, 256))
    except APIError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise APIError(413, "image_too_large", "Les dimensions de l'image sont trop grandes.") from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise APIError(400, "invalid_image", "L'image est corrompue ou son format est illisible.") from exc


def _png(array: np.ndarray) -> str:
    buffer = BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def render_visualization(sample: dict, values: np.ndarray, *, transfer: bool) -> Visualization:
    valid = sample["valid_mask"][0].numpy().astype(bool)
    if values.shape != valid.shape or not np.isfinite(values).all() or values.min() < 0 or values.max() > 1:
        raise ValueError("Carte d'explication invalide.")
    raw = sample["image"].permute(1, 2, 0).numpy()
    # Echelle fixe [0,1] pour l'erreur L1. Grad-CAM est normalise par l'API existante.
    strength = np.where(valid, values, 0)
    color = np.stack((strength, np.zeros_like(strength), 1 - strength), axis=-1)
    color[~valid] = 0
    alpha = (0.5 * strength)[..., None]
    overlay = raw * (1 - alpha) + color * alpha
    return Visualization(kind="gradcam" if transfer else "reconstruction_error",
                         description=("Grad-CAM du logit anomalie, attribution visuelle grossiere."
                                      if transfer else "Erreur absolue moyenne RGB de reconstruction, padding exclu."),
                         padding_top_bottom_left_right=sample["padding"].tolist(),
                         original_height_width=sample["original_size"].tolist(),
                         scale="relative_per_image_0_1" if transfer else "absolute_l1_0_1",
                         image_png_base64=_png(np.rint(raw * 255).astype(np.uint8)),
                         heatmap_png_base64=_png(np.rint(color * 255).astype(np.uint8)),
                         overlay_png_base64=_png(np.rint(overlay.clip(0, 1) * 255).astype(np.uint8)))
