"""Batch state is isolated from Sprint 1 inspections; no scientific model weights here."""
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base, utcnow


class InspectionBatch(Base):
    __tablename__ = 'inspection_batches'
    __table_args__ = (
        CheckConstraint("engine IN ('pytorch','onnxruntime')"),
        CheckConstraint("status IN ('queued','running','cancelling','completed','completed_with_errors','failed','cancelled')"),
        CheckConstraint('total BETWEEN 1 AND 50 AND processed BETWEEN 0 AND total'),
        CheckConstraint('normal_count >= 0 AND anomaly_count >= 0 AND error_count >= 0 AND cancelled_count >= 0'),
        CheckConstraint('processed = normal_count + anomaly_count + error_count + cancelled_count'),
        CheckConstraint('total_bytes > 0 AND total_bytes <= 104857600'),
        UniqueConstraint('owner_id', 'submission_key'),
        Index('ix_batches_owner_created', 'owner_id', 'created_at'),
        Index('ix_batches_queue', 'status', 'created_at'),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'))
    submission_key: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    category: Mapped[str] = mapped_column(ForeignKey('categories.name'))
    model: Mapped[str] = mapped_column(ForeignKey('model_families.name'))
    engine: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default='queued')
    total: Mapped[int] = mapped_column(Integer)
    total_bytes: Mapped[int] = mapped_column(Integer)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    normal_count: Mapped[int] = mapped_column(Integer, default=0)
    anomaly_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    cancelled_count: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    images_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    results_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    images_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BatchItem(Base):
    __tablename__ = 'batch_items'
    __table_args__ = (
        UniqueConstraint('batch_id', 'position'),
        CheckConstraint("status IN ('queued','running','retrying','completed','failed','cancelled')"),
        CheckConstraint("mime IN ('image/png','image/jpeg')"),
        CheckConstraint("engine IS NULL OR engine IN ('pytorch','onnxruntime')"),
        CheckConstraint("decision IS NULL OR decision IN ('normal','anomaly')"),
        CheckConstraint('position BETWEEN 1 AND 50 AND attempts BETWEEN 0 AND 3'),
        CheckConstraint('file_bytes > 0 AND file_bytes <= 10485760 AND length(file_sha256)=64'),
        CheckConstraint('anomaly_score IS NULL OR anomaly_score BETWEEN 0 AND 1'),
        CheckConstraint('threshold IS NULL OR threshold BETWEEN 0 AND 1'),
        CheckConstraint('inference_time_ms IS NULL OR inference_time_ms >= 0'),
        Index('ix_batch_items_claim', 'status', 'not_before', 'lease_until'),
        Index('ix_batch_items_batch_status', 'batch_id', 'status'),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey('inspection_batches.id', ondelete='CASCADE'))
    position: Mapped[int] = mapped_column(Integer)
    file_ref: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True)
    filename: Mapped[str] = mapped_column(String(160))
    file_sha256: Mapped[str] = mapped_column(String(64))
    file_bytes: Mapped[int] = mapped_column(Integer)
    mime: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default='queued')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claim_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_id: Mapped[UUID | None] = mapped_column(ForeignKey('model_releases.id'))
    engine: Mapped[str | None] = mapped_column(String(16))
    anomaly_score: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    decision: Mapped[str | None] = mapped_column(String(12))
    inference_time_ms: Mapped[float | None] = mapped_column(Float)
    upstream_request_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), unique=True)
    error_code: Mapped[str | None] = mapped_column(String(48))
    file_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BatchEvent(Base):
    __tablename__ = 'batch_events'
    __table_args__ = (Index('ix_batch_events_created', 'batch_id', 'created_at'),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey('inspection_batches.id', ondelete='CASCADE'))
    item_id: Mapped[UUID | None] = mapped_column(ForeignKey('batch_items.id', ondelete='SET NULL'))
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey('users.id'))
    kind: Mapped[str] = mapped_column(String(48))
    error_code: Mapped[str | None] = mapped_column(String(48))
    attempt: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
