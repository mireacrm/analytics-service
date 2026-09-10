"""Наполнение витрин и расчёт отчётов."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import models


async def mark_processed(session: AsyncSession, event_id: uuid.UUID, routing_key: str) -> bool:
    """False — событие уже обрабатывалось.

    Коммита здесь нет намеренно: отметка должна попасть в ту же транзакцию,
    что и запись факта.
    """
    statement = (
        insert(models.ProcessedEvent)
        .values(event_id=event_id, routing_key=routing_key)
        .on_conflict_do_nothing(index_elements=["event_id"])
        .returning(models.ProcessedEvent.event_id)
    )
    return await session.scalar(statement) is not None


# --- наполнение витрин ---


async def record_appointment_created(session: AsyncSession, **values) -> None:
    statement = (
        insert(models.AppointmentFact)
        .values(state=models.AppointmentState.CREATED, **values)
        .on_conflict_do_nothing(index_elements=["appointment_id"])
    )
    await session.execute(statement)


async def resolve_appointment(
    session: AsyncSession,
    appointment_id: uuid.UUID,
    state: models.AppointmentState,
    at: datetime,
) -> None:
    """Отмечает исход записи.

    Событие может прийти раньше, чем appointment.created: очереди у сервисов
    разные, порядок между ними не гарантирован. Поэтому если факта ещё нет —
    просто ничего не делаем, конверсия досчитается по создавшимся.
    """
    fact = await session.get(models.AppointmentFact, appointment_id)
    if fact is None:
        return
    fact.state = state
    fact.resolved_at = at


async def record_invoice_issued(session: AsyncSession, **values) -> None:
    statement = (
        insert(models.InvoiceFact).values(**values).on_conflict_do_nothing(
            index_elements=["invoice_id"]
        )
    )
    await session.execute(statement)


async def record_invoice_paid(
    session: AsyncSession,
    invoice_id: uuid.UUID,
    employee_id: uuid.UUID,
    commission_kopecks: int,
    paid_at: datetime,
) -> None:
    fact = await session.get(models.InvoiceFact, invoice_id)
    if fact is None:
        return
    fact.employee_id = employee_id
    fact.commission_kopecks = commission_kopecks
    fact.paid_at = paid_at


async def record_consumables(session: AsyncSession, rows: list[dict]) -> None:
    if rows:
        await session.execute(insert(models.ConsumableFact), rows)


async def record_client(
    session: AsyncSession, client_id: uuid.UUID, branch_id: uuid.UUID, at: datetime
) -> None:
    statement = (
        insert(models.ClientFact)
        .values(client_id=client_id, branch_id=branch_id, registered_at=at)
        .on_conflict_do_nothing(index_elements=["client_id"])
    )
    await session.execute(statement)


# --- отчёты ---


@dataclass(frozen=True, slots=True)
class Revenue:
    invoices: int
    total_kopecks: int
    average_kopecks: int


async def branch_revenue(
    session: AsyncSession, branch_id: uuid.UUID, since: datetime, until: datetime
) -> Revenue:
    """Выручка считается по оплаченным счетам: выставленный ещё не деньги."""
    query = select(
        func.count(), func.coalesce(func.sum(models.InvoiceFact.total_kopecks), 0)
    ).where(
        models.InvoiceFact.branch_id == branch_id,
        models.InvoiceFact.paid_at.is_not(None),
        models.InvoiceFact.paid_at >= since,
        models.InvoiceFact.paid_at < until,
    )
    count, total = (await session.execute(query)).one()
    average = int(total // count) if count else 0
    return Revenue(invoices=int(count), total_kopecks=int(total), average_kopecks=average)


def _duration():
    return models.AppointmentFact.ends_at - models.AppointmentFact.starts_at


@dataclass(frozen=True, slots=True)
class Workload:
    appointments: int
    completed: int
    busy_minutes: int
    commission_kopecks: int


async def employee_workload(
    session: AsyncSession, employee_id: uuid.UUID, since: datetime, until: datetime
) -> Workload:
    appointments_query = select(
        func.count(),
        func.count().filter(models.AppointmentFact.state == models.AppointmentState.COMPLETED),
        func.coalesce(
            func.sum(
                case(
                    (
                        models.AppointmentFact.state == models.AppointmentState.COMPLETED,
                        func.extract("epoch", _duration()) / 60,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
    ).where(
        models.AppointmentFact.employee_id == employee_id,
        models.AppointmentFact.starts_at >= since,
        models.AppointmentFact.starts_at < until,
    )
    total, completed, minutes = (await session.execute(appointments_query)).one()

    commission_query = select(
        func.coalesce(func.sum(models.InvoiceFact.commission_kopecks), 0)
    ).where(
        models.InvoiceFact.employee_id == employee_id,
        models.InvoiceFact.paid_at.is_not(None),
        models.InvoiceFact.paid_at >= since,
        models.InvoiceFact.paid_at < until,
    )
    commission = await session.scalar(commission_query)

    return Workload(
        appointments=int(total),
        completed=int(completed),
        busy_minutes=int(minutes),
        commission_kopecks=int(commission or 0),
    )


@dataclass(frozen=True, slots=True)
class Funnel:
    created: int
    completed: int
    cancelled: int
    pending: int

    @property
    def conversion(self) -> float:
        resolved = self.completed + self.cancelled
        return round(self.completed / resolved, 4) if resolved else 0.0


async def branch_funnel(
    session: AsyncSession, branch_id: uuid.UUID, since: datetime, until: datetime
) -> Funnel:
    query = (
        select(models.AppointmentFact.state, func.count())
        .where(
            models.AppointmentFact.branch_id == branch_id,
            models.AppointmentFact.starts_at >= since,
            models.AppointmentFact.starts_at < until,
        )
        .group_by(models.AppointmentFact.state)
    )
    counts = {state: int(count) for state, count in (await session.execute(query)).all()}

    completed = counts.get(models.AppointmentState.COMPLETED, 0)
    cancelled = counts.get(models.AppointmentState.CANCELLED, 0)
    pending = counts.get(models.AppointmentState.CREATED, 0)
    return Funnel(
        created=completed + cancelled + pending,
        completed=completed,
        cancelled=cancelled,
        pending=pending,
    )


@dataclass(frozen=True, slots=True)
class ConsumableUsage:
    consumable_id: uuid.UUID
    unit: str
    amount: float
    write_offs: int


async def consumables_usage(
    session: AsyncSession, branch_id: uuid.UUID, since: datetime, until: datetime
) -> list[ConsumableUsage]:
    query = (
        select(
            models.ConsumableFact.consumable_id,
            models.ConsumableFact.unit,
            func.sum(models.ConsumableFact.amount),
            func.count(),
        )
        .where(
            models.ConsumableFact.branch_id == branch_id,
            models.ConsumableFact.written_at >= since,
            models.ConsumableFact.written_at < until,
        )
        .group_by(models.ConsumableFact.consumable_id, models.ConsumableFact.unit)
        .order_by(func.sum(models.ConsumableFact.amount).desc())
    )

    return [
        ConsumableUsage(
            consumable_id=consumable_id,
            unit=unit,
            amount=float(amount),
            write_offs=int(write_offs),
        )
        for consumable_id, unit, amount, write_offs in (await session.execute(query)).all()
    ]
