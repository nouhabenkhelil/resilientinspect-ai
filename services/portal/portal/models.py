"""PostgreSQL business state only: never original images, heatmaps or OIDC tokens."""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("issuer", "subject"), CheckConstraint("role IN ('admin','ai_engineer','operator','auditor')"))
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    issuer: Mapped[str] = mapped_column(String(512))
    subject: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(24))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Session(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginFlow(Base):
    __tablename__ = "login_flows"
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    cookie_hash: Mapped[str] = mapped_column(String(64))
    nonce: Mapped[str] = mapped_column(String(128))
    verifier: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Category(Base):
    __tablename__ = "categories"
    name: Mapped[str] = mapped_column(String(24), primary_key=True)


class ModelFamily(Base):
    __tablename__ = "model_families"
    name: Mapped[str] = mapped_column(String(8), primary_key=True)


class ModelRelease(Base):
    __tablename__ = "model_releases"
    __table_args__ = (UniqueConstraint("family", "category", "checkpoint_sha256"),
                      CheckConstraint("length(checkpoint_sha256)=64 AND length(calibration_sha256)=64"))
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family: Mapped[str] = mapped_column(ForeignKey("model_families.name"))
    category: Mapped[str] = mapped_column(ForeignKey("categories.name"))
    checkpoint_sha256: Mapped[str] = mapped_column(String(64))
    calibration_sha256: Mapped[str] = mapped_column(String(64))


class Inspection(Base):
    __tablename__ = "inspections"
    __table_args__ = (CheckConstraint("engine IN ('pytorch','onnxruntime')"),
                      CheckConstraint("status IN ('processing','completed','failed')"),
                      CheckConstraint("anomaly_score IS NULL OR (anomaly_score >= 0 AND anomaly_score <= 1)"),
                      CheckConstraint("threshold IS NULL OR (threshold >= 0 AND threshold <= 1)"),
                      CheckConstraint("decision IS NULL OR decision IN ('normal','anomaly')"),
                      CheckConstraint("inference_time_ms IS NULL OR inference_time_ms >= 0"),
                      CheckConstraint("gateway_time_ms IS NULL OR gateway_time_ms >= 0"),
                      Index("ix_inspection_owner_created", "owner_id", "created_at"))
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(ForeignKey("categories.name"))
    model: Mapped[str] = mapped_column(ForeignKey("model_families.name"))
    release_id: Mapped[UUID | None] = mapped_column(ForeignKey("model_releases.id"))
    engine: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="processing")
    anomaly_score: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    decision: Mapped[str | None] = mapped_column(String(12))
    inference_time_ms: Mapped[float | None] = mapped_column(Float)
    gateway_time_ms: Mapped[float | None] = mapped_column(Float)
    gateway_request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    upstream_request_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), unique=True)
    image_sha256: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InspectionGrant(Base):
    __tablename__ = "inspection_grants"
    inspection_id: Mapped[UUID] = mapped_column(ForeignKey("inspections.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    granted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_actor_created", "actor_id", "created_at"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    resource_id: Mapped[UUID | None] = mapped_column(ForeignKey("inspections.id"))
    action: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16))
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class RateBucket(Base):
    __tablename__ = "rate_buckets"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    window: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class WorkLease(Base):
    __tablename__ = "work_leases"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    inspection_id: Mapped[UUID | None] = mapped_column(ForeignKey("inspections.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
