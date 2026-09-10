import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from mireacrm_common.deps import get_context, get_session
from mireacrm_common.lifespan import AppContext
from sqlalchemy.ext.asyncio import AsyncSession

from app import domain
from app.api import schemas
from app.infra import access

router = APIRouter(tags=["analytics"])


def period(
    since: datetime = Query(alias="from"), until: datetime = Query(alias="to")
) -> tuple[datetime, datetime]:
    return since, until


@router.get("/branches/{branch_id}/revenue", response_model=schemas.RevenueOut)
async def branch_revenue(
    branch_id: uuid.UUID,
    window: tuple[datetime, datetime] = Depends(period),
    session: AsyncSession = Depends(get_session),
    context: AppContext = Depends(get_context),
):
    """Выручка филиала. Название филиала подтягивается из core по gRPC:
    витрины хранят только идентификаторы."""
    since, until = window
    revenue = await domain.branch_revenue(session, branch_id, since, until)
    branch = await context.clients.branch(branch_id)

    return schemas.RevenueOut(
        branch_id=branch_id,
        branch_name=branch.name,
        since=since,
        until=until,
        invoices=revenue.invoices,
        total_kopecks=revenue.total_kopecks,
        average_kopecks=revenue.average_kopecks,
    )


@router.get("/employees/{employee_id}/workload", response_model=schemas.WorkloadOut)
async def employee_workload(
    employee_id: uuid.UUID,
    window: tuple[datetime, datetime] = Depends(period),
    session: AsyncSession = Depends(get_session),
):
    access.ensure_owner(employee_id, "загрузка сотрудника")

    since, until = window
    workload = await domain.employee_workload(session, employee_id, since, until)

    return schemas.WorkloadOut(
        employee_id=employee_id,
        since=since,
        until=until,
        appointments=workload.appointments,
        completed=workload.completed,
        busy_minutes=workload.busy_minutes,
        commission_kopecks=workload.commission_kopecks,
    )


@router.get("/branches/{branch_id}/funnel", response_model=schemas.FunnelOut)
async def branch_funnel(
    branch_id: uuid.UUID,
    window: tuple[datetime, datetime] = Depends(period),
    session: AsyncSession = Depends(get_session),
):
    """Конверсия: записались → пришли или отменили."""
    since, until = window
    funnel = await domain.branch_funnel(session, branch_id, since, until)

    return schemas.FunnelOut(
        branch_id=branch_id,
        since=since,
        until=until,
        created=funnel.created,
        completed=funnel.completed,
        cancelled=funnel.cancelled,
        pending=funnel.pending,
        conversion=funnel.conversion,
    )


@router.get("/reports/consumables", response_model=schemas.ConsumablesReportOut)
async def consumables_report(
    branch_id: uuid.UUID,
    window: tuple[datetime, datetime] = Depends(period),
    session: AsyncSession = Depends(get_session),
):
    since, until = window
    usage = await domain.consumables_usage(session, branch_id, since, until)

    return schemas.ConsumablesReportOut(
        branch_id=branch_id,
        since=since,
        until=until,
        items=[
            schemas.ConsumableUsageOut(
                consumable_id=item.consumable_id,
                unit=item.unit,
                amount=item.amount,
                write_offs=item.write_offs,
            )
            for item in usage
        ],
    )
