from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Index
)
from sqlalchemy.orm import relationship

from database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    bison_lead_id = Column(Integer, nullable=True)
    bison_inbox_id = Column(String(100), nullable=False)
    twenty_contact_id = Column(String(100), nullable=True, unique=True)
    twenty_opportunity_id = Column(String(100), nullable=True, unique=True)
    campaign_status = Column(String(50), nullable=False, default="New")
    lead_magnet_url = Column(Text, nullable=True)
    last_contact_date = Column(DateTime, nullable=True)
    follow_up_count = Column(Integer, nullable=False, default=0)
    original_reply_text = Column(Text, nullable=True)
    sentiment = Column(String(20), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    scheduled_tasks = relationship("ScheduledTask", back_populates="lead")
    logs = relationship("SystemLog", back_populates="lead")

    __table_args__ = (
        Index("ix_leads_status_contact", "campaign_status", "last_contact_date"),
    )


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    task_type = Column(String(50), nullable=False)  # lead_magnet, follow_up_1, follow_up_2, follow_up_3
    scheduled_time = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # pending, completed, cancelled, failed
    error_message = Column(Text, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    lead = relationship("Lead", back_populates="scheduled_tasks")

    __table_args__ = (
        Index("ix_tasks_status_time", "status", "scheduled_time"),
    )


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    action = Column(String(100), nullable=False)
    details = Column(Text, nullable=True)
    level = Column(String(20), nullable=False, default="info")  # info, warning, error
    timestamp = Column(DateTime, nullable=False, default=_utcnow)

    lead = relationship("Lead", back_populates="logs")

    __table_args__ = (
        Index("ix_logs_timestamp", "timestamp"),
        Index("ix_logs_level", "level"),
    )
