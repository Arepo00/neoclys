from sqlalchemy import Column, DateTime, Integer, String, Text, JSON, func, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Organization(Base):
    __tablename__ = "organizations"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    role = Column(String(50), nullable=False)
    password_hash = Column(String(255), nullable=False)


class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    type = Column(String(80), nullable=False)
    status = Column(String(40), nullable=False, default="queued")
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id = Column(Integer, primary_key=True)
    provider = Column(String(80), nullable=False)
    event_type = Column(String(120), nullable=False)
    payload = Column(JSON, nullable=False)
    signature = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
