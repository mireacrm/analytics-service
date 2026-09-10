"""Обработчики доменных событий.

Аналитика биндится на `#` и получает весь поток. События, которые ни в одну
витрину не ложатся, подтверждаются молча — иначе очередь встанет.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from mirea.events.v1 import events_pb2
from mireacrm_common.lifespan import AppContext

from app import domain, models

log = logging.getLogger(__name__)

Handler = Callable[[events_pb2.EventEnvelope], Awaitable[None]]


def _occurred(envelope: events_pb2.EventEnvelope) -> datetime:
    if envelope.HasField("occurred_at"):
        return envelope.occurred_at.ToDatetime(tzinfo=UTC)
    return datetime.now(UTC)


def build(context: AppContext) -> Handler:
    """Один обработчик на весь поток: отметка в inbox и запись факта идут
    одной транзакцией."""

    async def handler(envelope: events_pb2.EventEnvelope) -> None:
        async with context.session() as session:
            if not await domain.mark_processed(
                session, uuid.UUID(envelope.event_id), envelope.routing_key
            ):
                log.debug("событие уже обработано: %s", envelope.event_id)
                return

            await _apply(session, envelope)
            await session.commit()

    return handler


async def _apply(session, envelope: events_pb2.EventEnvelope) -> None:
    key = envelope.routing_key
    at = _occurred(envelope)

    if key == "appointment.created":
        payload = envelope.appointment_created
        await domain.record_appointment_created(
            session,
            appointment_id=uuid.UUID(payload.appointment_id),
            branch_id=uuid.UUID(payload.branch_id),
            employee_id=uuid.UUID(payload.employee_id),
            client_id=uuid.UUID(payload.client_id),
            service_id=uuid.UUID(payload.service_id),
            starts_at=payload.period.start_at.ToDatetime(tzinfo=UTC),
            ends_at=payload.period.end_at.ToDatetime(tzinfo=UTC),
            created_at=at,
        )

    elif key == "appointment.completed":
        await domain.resolve_appointment(
            session,
            uuid.UUID(envelope.appointment_completed.appointment_id),
            models.AppointmentState.COMPLETED,
            at,
        )

    elif key == "appointment.cancelled":
        await domain.resolve_appointment(
            session,
            uuid.UUID(envelope.appointment_cancelled.appointment_id),
            models.AppointmentState.CANCELLED,
            at,
        )

    elif key == "invoice.issued":
        payload = envelope.invoice_issued
        await domain.record_invoice_issued(
            session,
            invoice_id=uuid.UUID(payload.invoice_id),
            branch_id=uuid.UUID(payload.branch_id),
            client_id=uuid.UUID(payload.client_id),
            total_kopecks=payload.total.amount_kopecks,
            issued_at=at,
        )

    elif key == "invoice.paid":
        payload = envelope.invoice_paid
        await domain.record_invoice_paid(
            session,
            uuid.UUID(payload.invoice_id),
            uuid.UUID(payload.employee_id),
            payload.employee_commission.amount_kopecks,
            at,
        )

    elif key == "consumables.written_off":
        payload = envelope.consumables_written_off
        await domain.record_consumables(
            session,
            [
                {
                    "id": uuid.uuid4(),
                    "branch_id": uuid.UUID(payload.branch_id),
                    "appointment_id": uuid.UUID(payload.appointment_id),
                    "consumable_id": uuid.UUID(item.consumable_id),
                    "unit": item.unit,
                    "amount": item.amount,
                    "written_at": at,
                }
                for item in payload.items
            ],
        )

    elif key == "client.registered":
        payload = envelope.client_registered
        await domain.record_client(
            session, uuid.UUID(payload.client_id), uuid.UUID(payload.branch_id), at
        )

    else:
        # branch.opened, employee.hired, stock.low — справочные, в витрины
        # не ложатся. Отметка в inbox уже сделана, этого достаточно.
        log.debug("событие без витрины: %s", key)
