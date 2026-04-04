import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from toknx_coordinator.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    api_key_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    node_token_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    github_id: Mapped[str] = mapped_column(String(255), unique=True)
    github_username: Mapped[str] = mapped_column(String(255), index=True)
    max_nodes: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    credit_balance: Mapped["CreditBalance"] = relationship(back_populates="account", uselist=False)
    nodes: Mapped[list["Node"]] = relationship(back_populates="account")


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    committed_models: Mapped[list[str]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=list)
    hardware_spec: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="starting", index=True)
    tunnel_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    stake_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_ping_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    account: Mapped[Account] = relationship(back_populates="nodes")


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    hf_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    parameter_count: Mapped[int] = mapped_column(BigInteger)
    quantization: Mapped[str] = mapped_column(String(32))
    estimated_ram_gb: Mapped[float] = mapped_column()
    pricing_tier: Mapped[str] = mapped_column(String(8))
    credits_per_1k_tokens: Mapped[int] = mapped_column(Integer)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    node_id: Mapped[str | None] = mapped_column(ForeignKey("nodes.id"), nullable=True, index=True)
    model: Mapped[str] = mapped_column(String(255), index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    credits_consumer: Mapped[int] = mapped_column(BigInteger, default=0)
    credits_contributor: Mapped[int] = mapped_column(BigInteger, default=0)
    credits_coordinator: Mapped[int] = mapped_column(BigInteger, default=0)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreditBalance(Base):
    __tablename__ = "credits"

    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    total_earned: Mapped[int] = mapped_column(BigInteger, default=0)
    total_spent: Mapped[int] = mapped_column(BigInteger, default=0)

    account: Mapped[Account] = relationship(back_populates="credit_balance")


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    tx_type: Mapped[str] = mapped_column(String(64), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    node_id: Mapped[str | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Stake(Base):
    __tablename__ = "stakes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    node_id: Mapped[str | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("idx_nodes_committed_models", Node.committed_models, postgresql_using="gin")
Index("idx_nodes_online_only", Node.status)
Index("idx_jobs_active_status", Job.status, Job.created_at)
Index("idx_credit_tx_account_created", CreditTransaction.account_id, CreditTransaction.created_at)
