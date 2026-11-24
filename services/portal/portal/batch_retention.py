"""Batch-only retention. Never deletes Sprint 1 inspections, profiles or scientific files."""
import argparse
from datetime import timedelta
import json
from uuid import UUID
from sqlalchemy import select
from .batch_config import BatchConfig, WorkerConfig
from .batch_models import BatchItem, InspectionBatch
from .batch_queue import TERMINAL, event
from .batch_storage import PrivateStorage
from .models import AuditEvent, utcnow
from .security import Database


async def purge(db, config, *, execute=False, now=None):
    now = now or utcnow()
    storage = PrivateStorage(config)
    counts = {'images': 0, 'batches': 0, 'orphans': 0, 'execute': execute}
    async with db.sessions() as session:
        batches = (await session.execute(select(InspectionBatch).where(InspectionBatch.status.in_(TERMINAL),
            (InspectionBatch.images_expires_at <= now) | (InspectionBatch.results_expires_at <= now))
            .order_by(InspectionBatch.created_at).with_for_update(skip_locked=True).limit(100))).scalars().all()
        for batch in batches:
            items = (await session.execute(select(BatchItem).where(BatchItem.batch_id == batch.id))).scalars().all()
            for item in items:
                if item.file_deleted_at is None:
                    counts['images'] += 1
                    if execute:
                        storage.delete(item.file_ref)
                        item.file_deleted_at = now
            if batch.results_expires_at <= now:
                counts['batches'] += 1
                if execute:
                    # Purge correlation is the removed batch UUID, with no FK to Sprint 1 inspections.
                    session.add(AuditEvent(action='batch.results_purged', outcome='accepted', request_id=batch.id))
                    await session.delete(batch)  # FK cascades affect only batch_items and batch_events.
            elif execute and batch.images_purged_at is None:
                batch.images_purged_at = now
                event(session, batch, 'retention.images_purged')
        if execute: await session.commit()
        # Recover only old UUID-only files not referenced by any batch after an upload crash.
        if storage.ready():
            cutoff = (now - timedelta(hours=config.image_retention_hours)).timestamp()
            for path in storage.root.iterdir():
                if len(path.name) != 32 or path.is_symlink() or not path.is_file() or path.stat().st_mtime > cutoff:
                    continue
                try: ref = UUID(hex=path.name)
                except ValueError: continue
                if (await session.execute(select(BatchItem.id).where(BatchItem.file_ref == ref))).first(): continue
                counts['orphans'] += 1
                if execute:
                    storage.delete(ref)
                    session.add(AuditEvent(action='batch.orphan_purged', outcome='accepted', request_id=ref))
            if execute: await session.commit()
    return counts


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Apply configured batch-only retention; default is dry-run')
    args = parser.parse_args()
    db = Database(WorkerConfig.from_env())
    try: print(json.dumps(await purge(db, BatchConfig.from_env(), execute=args.execute)))
    finally: await db.engine.dispose()


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
