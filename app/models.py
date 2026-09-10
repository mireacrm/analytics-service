import enum
import uuid
from datetime import datetime
from typing import Annotated

from sqlalchemy import BigInteger, DateTime, Enum, Float, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Витрины. Собственных фактов сервис не создаёт — всё выводится из событий
# других сервисов. В чужие базы аналитика не ходит, только слушает шину.


class Base(DeclarativeBase):
    pass


UuidPk = Annotated[
    uuid.UUID, mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
]
CreatedAt = Annotated[
    datetime, mapped_column(DateTime(timezone=True), server_default=func.now())
]


class AppointmentState(enum.StrEnum):
    CREATED = "created"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AppointmentFact(Base):
    """Жизненный цикл записи: создана → завершена или отменена.

    Одна строка на запись, а не на событие: витрина конверсии считается
    группировкой по состоянию.
    """

    __tablename__ = "appointment_facts"

    appointment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    service_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[AppointmentState] = mapped_column(
        Enum(AppointmentState, name="appointment_state"), default=AppointmentState.CREATED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class InvoiceFact(Base):
    __tablename__ = "invoice_facts"

    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    total_kopecks: Mapped[int] = mapped_column(BigInteger)
    commission_kopecks: Mapped[int] = mapped_column(BigInteger, default=0)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConsumableFact(Base):
    __tablename__ = "consumable_facts"

    id: Mapped[UuidPk]
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    consumable_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    appointment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    unit: Mapped[str] = mapped_column(String(16))
    amount: Mapped[float] = mapped_column(Float)
    # Время наступления события, а не вставки: иначе догоняющая очередь
    # разложит факты по датам обработки и отчёты за период поедут.
    written_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ClientFact(Base):
    __tablename__ = "client_facts"

    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProcessedEvent(Base):
    """Inbox: RabbitMQ доставляет at-least-once.

    Отметка пишется той же транзакцией, что и запись факта — иначе упавшая
    обработка оставит событие помеченным, и повтор молча пропустит его.
    """

    __tablename__ = "processed_events"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    routing_key: Mapped[str] = mapped_column(String(64))
    processed_at: Mapped[CreatedAt]
