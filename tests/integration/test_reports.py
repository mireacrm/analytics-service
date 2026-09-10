"""Витрины против настоящего Postgres."""

import uuid
from datetime import UTC, datetime, timedelta

from app import domain, models

BRANCH = uuid.uuid4()
EMPLOYEE = uuid.uuid4()
DAY = datetime(2026, 9, 15, tzinfo=UTC)
WINDOW = (DAY, DAY + timedelta(days=1))


async def add_appointment(session, *, hour: int, minutes: int = 60, employee=EMPLOYEE):
    appointment_id = uuid.uuid4()
    await domain.record_appointment_created(
        session,
        appointment_id=appointment_id,
        branch_id=BRANCH,
        employee_id=employee,
        client_id=uuid.uuid4(),
        service_id=uuid.uuid4(),
        starts_at=DAY + timedelta(hours=hour),
        ends_at=DAY + timedelta(hours=hour, minutes=minutes),
        created_at=DAY,
    )
    return appointment_id


async def add_paid_invoice(session, *, total: int, commission: int, at: datetime):
    invoice_id = uuid.uuid4()
    await domain.record_invoice_issued(
        session,
        invoice_id=invoice_id,
        branch_id=BRANCH,
        client_id=uuid.uuid4(),
        total_kopecks=total,
        issued_at=at,
    )
    await domain.record_invoice_paid(session, invoice_id, EMPLOYEE, commission, at)
    return invoice_id


class TestInbox:
    async def test_duplicate_event_ignored(self, session):
        event_id = uuid.uuid4()

        assert await domain.mark_processed(session, event_id, "appointment.created")
        assert not await domain.mark_processed(session, event_id, "appointment.created")

    async def test_rollback_releases_mark(self, session):
        """Отметка и факт живут в одной транзакции: откат снимает обе."""
        event_id = uuid.uuid4()
        await domain.mark_processed(session, event_id, "appointment.created")
        await session.rollback()

        assert await domain.mark_processed(session, event_id, "appointment.created")


class TestRevenue:
    async def test_counts_only_paid(self, session):
        await add_paid_invoice(
            session, total=520000, commission=208000, at=DAY + timedelta(hours=2)
        )
        await domain.record_invoice_issued(
            session,
            invoice_id=uuid.uuid4(),
            branch_id=BRANCH,
            client_id=uuid.uuid4(),
            total_kopecks=999999,
            issued_at=DAY,
        )
        await session.commit()

        revenue = await domain.branch_revenue(session, BRANCH, *WINDOW)

        assert revenue.invoices == 1
        assert revenue.total_kopecks == 520000

    async def test_average_cheque(self, session):
        await add_paid_invoice(session, total=100000, commission=0, at=DAY + timedelta(hours=1))
        await add_paid_invoice(session, total=300000, commission=0, at=DAY + timedelta(hours=2))
        await session.commit()

        revenue = await domain.branch_revenue(session, BRANCH, *WINDOW)

        assert revenue.average_kopecks == 200000

    async def test_empty_period(self, session):
        revenue = await domain.branch_revenue(session, BRANCH, *WINDOW)

        assert revenue == domain.Revenue(invoices=0, total_kopecks=0, average_kopecks=0)


class TestFunnel:
    async def test_counts_by_state(self, session):
        completed = await add_appointment(session, hour=9)
        cancelled = await add_appointment(session, hour=11)
        await add_appointment(session, hour=13)
        await domain.resolve_appointment(
            session, completed, models.AppointmentState.COMPLETED, DAY
        )
        await domain.resolve_appointment(
            session, cancelled, models.AppointmentState.CANCELLED, DAY
        )
        await session.commit()

        funnel = await domain.branch_funnel(session, BRANCH, *WINDOW)

        assert (funnel.created, funnel.completed, funnel.cancelled, funnel.pending) == (3, 1, 1, 1)
        assert funnel.conversion == 0.5

    async def test_unknown_appointment_ignored(self, session):
        """Событие исхода может опередить создание: очереди у сервисов разные."""
        await domain.resolve_appointment(
            session, uuid.uuid4(), models.AppointmentState.COMPLETED, DAY
        )
        await session.commit()

        funnel = await domain.branch_funnel(session, BRANCH, *WINDOW)
        assert funnel.created == 0


class TestWorkload:
    async def test_busy_minutes_count_completed_only(self, session):
        completed = await add_appointment(session, hour=9, minutes=90)
        await add_appointment(session, hour=12, minutes=60)
        await domain.resolve_appointment(
            session, completed, models.AppointmentState.COMPLETED, DAY
        )
        await add_paid_invoice(
            session, total=520000, commission=208000, at=DAY + timedelta(hours=3)
        )
        await session.commit()

        workload = await domain.employee_workload(session, EMPLOYEE, *WINDOW)

        assert workload.appointments == 2
        assert workload.completed == 1
        assert workload.busy_minutes == 90
        assert workload.commission_kopecks == 208000

    async def test_other_employee_not_counted(self, session):
        await add_appointment(session, hour=9, employee=uuid.uuid4())
        await session.commit()

        workload = await domain.employee_workload(session, EMPLOYEE, *WINDOW)
        assert workload.appointments == 0


class TestConsumables:
    async def test_grouped_and_sorted(self, session):
        paint, oxidizer = uuid.uuid4(), uuid.uuid4()
        await domain.record_consumables(
            session,
            [
                {"id": uuid.uuid4(), "branch_id": BRANCH, "appointment_id": uuid.uuid4(),
                 "consumable_id": paint, "unit": "г", "amount": 60, "written_at": DAY},
                {"id": uuid.uuid4(), "branch_id": BRANCH, "appointment_id": uuid.uuid4(),
                 "consumable_id": paint, "unit": "г", "amount": 40, "written_at": DAY},
                {"id": uuid.uuid4(), "branch_id": BRANCH, "appointment_id": uuid.uuid4(),
                 "consumable_id": oxidizer, "unit": "мл", "amount": 500, "written_at": DAY},
            ],
        )
        await session.commit()

        usage = await domain.consumables_usage(session, BRANCH, *WINDOW)

        assert [item.amount for item in usage] == [500.0, 100.0]
        assert usage[1].consumable_id == paint
        assert usage[1].write_offs == 2
