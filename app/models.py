from datetime import datetime, timezone
from urllib.parse import quote_plus

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, event, text
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

class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, index=True)
    event_number = Column(String, nullable=False)
    train_bus_number = Column("vehicle_number", String, nullable=False)
    timestamp = Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc))
    driver_name = Column(String(120), nullable=False, default="Unknown Driver")
    location = Column(String(255), nullable=False, default="Unknown Location")
    description = Column(Text, nullable=True, default="No description available.")
    status = Column(String(30), nullable=False, default="created")

    @property
    def event_id(self) -> int:
        return self.id

    @property
    def google_maps_url(self) -> str:
        return f"https://www.google.com/maps/search/?api=1&query={quote_plus(self.location or '')}"


@event.listens_for(Event, "before_insert")
def assign_event_number(mapper, connection, target) -> None:
    if getattr(target, "event_number", None):
        return

    latest = connection.execute(
        text(
            "SELECT event_number FROM events "
            "WHERE event_number LIKE 'E%' "
            "ORDER BY CAST(SUBSTR(event_number, 2) AS INTEGER) DESC "
            "LIMIT 1"
        )
    ).scalar()

    next_number = 1001
    if isinstance(latest, str) and latest.startswith("E"):
        try:
            next_number = int(latest[1:]) + 1
        except ValueError:
            next_number = 1001

    target.event_number = f"E{next_number}"
