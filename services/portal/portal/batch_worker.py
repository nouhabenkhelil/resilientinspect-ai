"""CPU queue worker. One PostgreSQL advisory slot by default; no PyTorch imports."""
import asyncio
from contextlib import suppress
import json
import logging
from pathlib import Path
import time
from uuid import UUID
import httpx2 as httpx
from sqlalchemy import text
from .batch_config import BatchConfig, WorkerConfig
from .batch_queue import claim, finalize
from .batch_retention import purge
from .batch_science import infer, metadata
from .batch_storage import PrivateStorage
from .security import Database, PublicError, release_lease

HEARTBEAT = Path('/tmp/ri-batch-heartbeat.json')
logger = logging.getLogger('portal.batch')
for name in ('httpx', 'httpx2', 'httpcore', 'httpcore2', 'sqlalchemy.engine'):
    logging.getLogger(name).setLevel(logging.WARNING)


async def process(db, client, settings, config, reservation):
    batch, item, work_lease = reservation
    result, selected, error = None, None, None
    try:
        async with asyncio.timeout(settings.inference_timeout):
            content = await asyncio.to_thread(PrivateStorage(config).read, item.file_ref, item.file_sha256, config.max_file_bytes)
            selected = await metadata(client, batch.model, batch.category, batch.engine)
            result = await infer(client, batch, item, content, selected)
            result['request_id'] = UUID(result['request_id'])
    except PublicError as problem:
        error = problem.code
    except (TimeoutError, httpx.HTTPError):
        error = 'inference_timeout'
    except Exception:
        error = 'processing_failed'  # No raw exceptions, file paths, tokens or SQL parameters in logs.
    try:
        await finalize(db, config, batch.id, item.id, item.claim_token, result=result, selected=selected, error=error)
    finally:
        await release_lease(db, work_lease)


async def heartbeat(db, state):
    while True:
        try:
            async with db.engine.connect() as connection:
                await connection.execute(text('SELECT 1'))
            data = {'at': time.time(), 'status': 'ready' if state['slot'] is not None else 'standby', 'slot': state['slot']}
            temp = HEARTBEAT.with_suffix('.tmp')
            temp.write_text(json.dumps(data))
            temp.replace(HEARTBEAT)
        except Exception:
            logger.warning('action=worker.heartbeat_failed')
        await asyncio.sleep(5)


async def run():
    settings, config = WorkerConfig.from_env(), BatchConfig.from_env()
    db = Database(settings)
    state = {'slot': None}
    pulse = asyncio.create_task(heartbeat(db, state))
    last_purge = 0
    try:
        async with db.engine.connect() as slot_connection:
            slot_pid = (await slot_connection.execute(text('SELECT pg_backend_pid()'))).scalar_one()
            await slot_connection.commit()
            while state['slot'] is None:
                for slot in range(config.worker_concurrency):
                    locked = (await slot_connection.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': 1865432300 + slot})).scalar_one()
                    await slot_connection.commit()
                    if locked:
                        state['slot'] = slot
                        break
                if state['slot'] is None: await asyncio.sleep(2)
            async with httpx.AsyncClient(base_url=settings.scientific_url, timeout=settings.inference_timeout,
                follow_redirects=False, trust_env=False, limits=httpx.Limits(max_connections=2, max_keepalive_connections=1)) as client:
                logger.info('action=worker.ready slot=%s', state['slot'])
                while True:
                    try:
                        # A disconnected advisory-lock connection must stop this worker before any new claim.
                        current_pid = (await slot_connection.execute(text('SELECT pg_backend_pid()'))).scalar_one()
                        if current_pid != slot_pid: raise SystemExit('Worker slot connection changed; restart required')
                        await slot_connection.commit()
                        reservation = await claim(db, settings, config)
                        if reservation: await process(db, client, settings, config, reservation)
                        else: await asyncio.sleep(0.5)
                        if time.monotonic() - last_purge > 60:
                            await purge(db, config, execute=True)
                            last_purge = time.monotonic()
                    except (ConnectionError, OSError):
                        raise
                    except Exception:
                        logger.warning('action=worker.iteration_failed')
                        # Check the slot connection is still the same live PostgreSQL session.
                        if slot_connection.invalidated: raise
                        await asyncio.sleep(2)
    finally:
        pulse.cancel()
        with suppress(asyncio.CancelledError): await pulse
        await db.engine.dispose()


def health():
    try:
        value = json.loads(HEARTBEAT.read_text())
        return 0 if value['status'] == 'ready' and 0 <= time.time() - value['at'] < 20 else 1
    except (OSError, ValueError, KeyError): return 1


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    if '--health' in sys.argv: raise SystemExit(health())
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.error('action=worker.stopped')
        raise SystemExit(1) from None
