
"""
SQLAlchemy database models for Araaz Delights.
"""

from datetime import date, datetime, time

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from services.db import Base


class Customer(Base):
    """Database model representing a restaurant customer/guest CRM profile."""

    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    phone: Mapped[str | None] = mapped_column(
        String(30),
        unique=True,
        index=True,
        nullable=True,
    )

    vip_tier: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="Standard",
    )

    total_visits: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    dietary_preferences: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    seating_preference: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    last_visit_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # One-to-many relationship: One customer can have multiple reservations
    reservations: Mapped[list["Reservation"]] = relationship(
        "Reservation",
        back_populates="customer",
        cascade="all, delete-orphan",
    )


class Reservation(Base):
    """Database model representing a restaurant reservation."""

    __tablename__ = "reservations"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    customer_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("customers.id"),
        nullable=True,
        index=True,
    )

    customer_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    customer_phone: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    customer_email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    restaurant_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="rest_01",
    )

    reservation_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    reservation_time: Mapped[time] = mapped_column(
        Time,
        nullable=False,
    )

    guest_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    seating_preference: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    special_requests: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    table_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="confirmed",
    )

    hold_token: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    calendar_event_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # Many-to-one relationship: Each reservation links back to its Customer profile
    customer: Mapped["Customer | None"] = relationship(
        "Customer",
        back_populates="reservations",
    )
