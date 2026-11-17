
"""
SQLAlchemy database models for Araaz Delights.
"""

from datetime import date, datetime, time

from sqlalchemy import (
    Date,
    DateTime,
    Integer,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from services.db import Base


class Reservation(Base):
    """Database model representing a restaurant reservation."""

    __tablename__ = "reservations"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
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
