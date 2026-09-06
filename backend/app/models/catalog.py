from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Marketplace(Base):
    __tablename__ = "marketplaces"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default="BRL")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    adapter_class: Mapped[str] = mapped_column(Text, nullable=False)
    # Config não-secreta. Credenciais vivem só em env/Vault.
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("marketplace_id", "external_product_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    marketplace_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("marketplaces.id"), nullable=False
    )
    external_product_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_shop_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category_path: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    product_url: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)


class ProductSnapshot(Base):
    """Append-only. Preço muda; a decisão de ontem precisa do preço de ontem."""

    __tablename__ = "product_snapshots"
    __table_args__ = (Index("ix_product_snapshots_product_id_captured_at", "product_id",
                            "captured_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    original_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    commission_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    commission_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    rating_count: Mapped[int | None] = mapped_column(Integer)
    sales_volume: Mapped[int | None] = mapped_column(Integer)
    stock: Mapped[int | None] = mapped_column(Integer)
    # {"sales_volume": false, ...} — ausência nunca vira zero.
    data_available: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
