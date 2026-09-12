"""
SQLAlchemy 2 Async declarative models for Telegram Email Image Delivery Bot.
Defines schemas and indexes for Orders, Images, Settings, AuthorizedUsers, ClientGroups, and Loaders tables
supporting two-group reply-based workflow, role-based user management, Group Category Routing (v1.2),
Multi Loader Approval System, and Category A Only Price Workflow with prompt & calculator tracking (v1.22.0).
"""

from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import String, Integer, BigInteger, DateTime, ForeignKey, Index, Float
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base model class."""
    pass


class Settings(Base):
    """
    Stores dynamic application settings and group configurations.
    Maintains a single record (id=1).
    source_group_id: Client Group ID (where customers send orders)
    delivery_group_id: Loader Group ID (where bot forwards orders & loaders reply)
    payment_review_group_id: Payment Review Group ID (for Category B orders)
    """

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    source_group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source_group_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delivery_group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    delivery_group_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payment_review_group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    payment_review_group_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    def __repr__(self) -> str:
        return f"<Settings(id={self.id}, client_group={self.source_group_id}, loader_group={self.delivery_group_id}, payment_group={self.payment_review_group_id})>"


class ClientGroup(Base):
    """
    Stores Client Group category assignments ('A' or 'B').
    Category A: Trusted Groups (Direct to Loader Group)
    Category B: Payment Required Groups (Forward to Payment Review Group)
    """

    __tablename__ = "client_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    group_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    category: Mapped[str] = mapped_column(String(10), nullable=False, default="A")  # 'A' or 'B'
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    def __repr__(self) -> str:
        return f"<ClientGroup(chat_id={self.chat_id}, category='{self.category}')>"


class Loader(Base):
    """
    Stores Loader Groups for Multi-Loader Category B approval system.
    """

    __tablename__ = "loaders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    loader_name: Mapped[str] = mapped_column(String(255), nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    def __repr__(self) -> str:
        return f"<Loader(id={self.id}, name='{self.loader_name}', group_id={self.group_id})>"


class GroupTotal(Base):
    """
    Stores per-group running totals and accounting state for Super Admin calculator.
    chat_id: Telegram chat/group ID (Primary Key)
    total: Current group balance
    previous_total: Previous balance before last operation (for /undo)
    last_amount: Last added/evaluated amount
    """

    __tablename__ = "group_totals"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    previous_total: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:
        return f"<GroupTotal(chat_id={self.chat_id}, total={self.total}, previous={self.previous_total})>"


class Order(Base):
    """
    Represents an Order record in the two-group reply-based workflow.
    Tracks client message, forwarded loader message, loader group ID, status, package details, category ('A'/'B'), price, price prompt msg ID, price msg ID, and stored image file_ids.
    """

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    package: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    original_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    loader_group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    loader_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="Pending", index=True)  # Pending, Pending Approval, Pending Payment, Approved, Rejected, Delivered, Cancelled, Expired
    category: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default="A")  # 'A' or 'B'
    price: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    price_prompt_msg_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    price_msg_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    media_group_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True
    )

    # Relationship to images ordered by position
    images: Mapped[List["Image"]] = relationship(
        "Image",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="Image.position"
    )

    def __repr__(self) -> str:
        img_count = len(self.__dict__['images']) if 'images' in self.__dict__ else self.image_count
        return f"<Order(id={self.id}, email='{self.email}', category='{self.category}', price='{self.price}', status='{self.status}', images={img_count})>"


class Image(Base):
    """
    Represents an individual image stored within an order.
    Supports photos and photo documents. Stores telegram file_id only.
    """

    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    telegram_file_id: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False, default="photo")  # 'photo' or 'document'
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Many-to-one relationship to Order
    order: Mapped["Image"] = relationship("Order", back_populates="images")

    def __repr__(self) -> str:
        return f"<Image(id={self.id}, order_id={self.order_id}, file_type='{self.file_type}', position={self.position})>"


# Compound index for email + creation timestamp queries
Index("idx_orders_email_created_desc", Order.email, Order.created_at.desc())
