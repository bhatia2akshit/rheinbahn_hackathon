from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    internal_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    label_de: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)


class PoliceDepartment(Base):
    __tablename__ = "police_departments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    postal_code_start: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    postal_code_end: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    phone_number: Mapped[str] = mapped_column(String(30), nullable=False)

    incidents: Mapped[list["Incident"]] = relationship(back_populates="police_department")


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    postal_code: Mapped[str] = mapped_column(String(5), nullable=False, index=True)
    detected_categories: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        doc="JSON-encoded list of detected German category labels",
    )
    selected_action: Mapped[str] = mapped_column(String(50), nullable=False)
    police_department_id: Mapped[int | None] = mapped_column(
        ForeignKey("police_departments.id"),
        nullable=True,
    )
    generated_script: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    police_department: Mapped[PoliceDepartment | None] = relationship(back_populates="incidents")

