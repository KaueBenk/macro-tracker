import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Connection
from sqlalchemy.orm import DeclarativeBase, Mapped, Mapper, mapped_column, relationship

from app.text import normalize_search_text


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    tokens: Mapped[list["ApiToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    foods: Mapped[list["Food"]] = relationship(back_populates="user")
    entries: Mapped[list["Entry"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    goals: Mapped[list["Goal"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class ApiToken(TimestampMixin, Base):
    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="tokens")


class Food(TimestampMixin, Base):
    __tablename__ = "foods"
    __table_args__ = (
        Index(
            "uq_food_user_name_brand",
            "user_id",
            text("lower(name)"),
            text("coalesce(brand, '')"),
            unique=True,
        ),
        Index(
            "uq_food_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source is not null"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str | None] = mapped_column(String(200))
    kcal: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    protein_g: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    carbs_g: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    fat_g: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    serving_label: Mapped[str | None] = mapped_column(String(100))
    serving_grams: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    source: Mapped[str | None] = mapped_column(String(20))
    source_ref: Mapped[str | None] = mapped_column(String(50))
    category: Mapped[str | None] = mapped_column(String(100))
    search_text: Mapped[str | None] = mapped_column(Text)
    user: Mapped[User | None] = relationship(back_populates="foods")


@event.listens_for(Food, "before_insert")
@event.listens_for(Food, "before_update")
def update_food_search_text(_: Mapper[Food], __: Connection, target: Food) -> None:
    target.search_text = normalize_search_text(target.name, target.brand, target.category)


class Meal(str, enum.Enum):
    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"
    snack = "snack"
    other = "other"


class Entry(TimestampMixin, Base):
    __tablename__ = "entries"
    __table_args__ = (Index("ix_entries_user_logged_at", "user_id", "logged_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    meal: Mapped[Meal] = mapped_column(Enum(Meal, name="meal"))
    food_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("foods.id", ondelete="SET NULL"))
    description: Mapped[str | None] = mapped_column(Text)
    quantity_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    kcal: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    protein_g: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    carbs_g: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    fat_g: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    user: Mapped[User] = relationship(back_populates="entries")
    food: Mapped[Food | None] = relationship()


class Goal(TimestampMixin, Base):
    __tablename__ = "goals"
    __table_args__ = (UniqueConstraint("user_id", "effective_from", name="uq_goal_user_effective"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    effective_from: Mapped[date] = mapped_column(Date)
    kcal: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    protein_g: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    carbs_g: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    fat_g: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    user: Mapped[User] = relationship(back_populates="goals")


class OAuthClient(Base):
    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    # The MCP SDK compares client secrets in cleartext during client authentication.
    client_secret: Mapped[str | None] = mapped_column(Text)
    client_metadata: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class OAuthAuthCode(Base):
    __tablename__ = "oauth_auth_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(255))
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    code_challenge: Mapped[str] = mapped_column(String(255))
    redirect_uri: Mapped[str] = mapped_column(Text)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column()
    resource: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"
    __table_args__ = (
        Index("ix_oauth_tokens_user_id", "user_id"),
        Index("ix_oauth_tokens_client_id", "client_id"),
    )

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    client_id: Mapped[str] = mapped_column(String(255))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    resource: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parent_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class OAuthPendingAuth(Base):
    __tablename__ = "oauth_pending_auth"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[str] = mapped_column(String(255))
    state: Mapped[str | None] = mapped_column(Text)
    login_state: Mapped[str | None] = mapped_column(Text, unique=True)
    browser_hash: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    code_challenge: Mapped[str] = mapped_column(String(255))
    redirect_uri: Mapped[str] = mapped_column(Text)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column()
    resource: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
