"""Call the unchanged scientific service, validate its identity and original threshold."""
import math
from uuid import UUID
import httpx2 as httpx
from sqlalchemy import select, text
from .models import ModelRelease
from .security import PublicError

MODELS = {'B0', 'A1', 'T0', 'T1', 'T2'}
CATEGORIES = {'bottle', 'hazelnut', 'leather'}
ENGINES = {'pytorch', 'onnxruntime'}


async def metadata(client, model, category, engine):
    try:
        response = await client.get('/model/metadata', params={'model': model, 'category': category})
        if response.status_code != 200 or len(response.content) > 2 * 1024 * 1024:
            raise PublicError(503, 'inference_unavailable')
        items = response.json()['models']
        if len(items) != 1 or items[0]['model'] != model or items[0]['category'] != category:
            raise PublicError(502, 'model_binding_mismatch')
        selected = items[0]
        if engine not in selected.get('available_engines', ['pytorch']):
            raise PublicError(503, 'onnx_unavailable' if engine == 'onnxruntime' else 'model_unavailable', 'Ce moteur est indisponible. Aucun repli automatique.')
        return selected
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        raise PublicError(503, 'inference_unavailable') from None


async def infer(client, batch, item, content, selected, visualize=False):
    try:
        response = await client.post('/predict/visualize' if visualize else '/predict',
            data={'model': batch.model, 'category': batch.category, 'engine': batch.engine},
            files={'file': ('inspection.png' if item.mime == 'image/png' else 'inspection.jpg', content, item.mime)},
            headers={'X-Portal-Request-ID': str(item.id)})
        if response.status_code != 200:
            codes = {'onnx_unavailable', 'model_unavailable', 'explanation_divergence', 'invalid_image', 'image_too_large'}
            try: code = response.json().get('code')
            except ValueError: code = None
            raise PublicError(response.status_code if response.status_code in {400, 409, 413, 415, 422, 503} else 503,
                              code if code in codes else 'inference_unavailable')
        if len(response.content) > 6 * 1024 * 1024:
            raise ValueError('bounded response required')
        result = response.json()
        if (result.get('model') != batch.model or result.get('category') != batch.category or result.get('engine') != batch.engine
                or result.get('version') != selected['checkpoint_sha256'] or result.get('threshold') != selected['threshold']
                or not all(type(result.get(k)) in (int, float) and math.isfinite(result[k]) for k in ('anomaly_score', 'threshold', 'inference_time_ms'))
                or not (0 <= result['anomaly_score'] <= 1 and 0 <= result['threshold'] <= 1 and result['inference_time_ms'] >= 0)
                or result.get('decision') != ('anomaly' if result['anomaly_score'] > result['threshold'] else 'normal')):
            raise ValueError('scientific binding mismatch')
        UUID(result['request_id'])
        return result
    except (httpx.HTTPError, TimeoutError):
        raise PublicError(504, 'inference_timeout') from None
    except (KeyError, ValueError, TypeError):
        raise PublicError(502, 'invalid_inference_response') from None


async def release_reference(session, batch, selected):
    await session.execute(text('SELECT pg_advisory_xact_lock(1865432192)'))
    release = (await session.execute(select(ModelRelease).where(ModelRelease.family == batch.model,
        ModelRelease.category == batch.category, ModelRelease.checkpoint_sha256 == selected['checkpoint_sha256']))).scalar_one_or_none()
    if release is None:
        release = ModelRelease(family=batch.model, category=batch.category, checkpoint_sha256=selected['checkpoint_sha256'],
                               calibration_sha256=selected['calibration_sha256'])
        session.add(release)
        await session.flush()
    elif release.calibration_sha256 != selected['calibration_sha256']:
        raise PublicError(502, 'calibration_binding_mismatch')
    return release.id
