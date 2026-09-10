"""Представления отчётов в HTTP-ответах."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class Period(BaseModel):
    since: datetime
    until: datetime


class RevenueOut(Period):
    branch_id: uuid.UUID
    branch_name: str
    invoices: int
    total_kopecks: int
    average_kopecks: int


class WorkloadOut(Period):
    employee_id: uuid.UUID
    appointments: int
    completed: int
    busy_minutes: int
    commission_kopecks: int


class FunnelOut(Period):
    branch_id: uuid.UUID
    created: int
    completed: int
    cancelled: int
    pending: int
    conversion: float


class ConsumableUsageOut(BaseModel):
    consumable_id: uuid.UUID
    unit: str
    amount: float
    write_offs: int


class ConsumablesReportOut(Period):
    branch_id: uuid.UUID
    items: list[ConsumableUsageOut]
