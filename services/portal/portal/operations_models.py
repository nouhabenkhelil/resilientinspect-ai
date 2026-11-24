"""Small service heartbeat ledger; never scientific state or user metrics labels."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base


class ServiceHeartbeat(Base):
    __tablename__ = 'service_heartbeats'
    service: Mapped[str] = mapped_column(String(16), primary_key=True)
    slot: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(12), default='ready')
    starts: Mapped[int] = mapped_column(Integer, default=1)
    failures: Mapped[int] = mapped_column(Integer, default=0)
