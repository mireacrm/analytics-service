"""Загрузка видна только своя: проверка на границе HTTP, база настоящая."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from mireacrm_common import identity

from app import domain

DAY = datetime(2026, 9, 15, tzinfo=UTC)
SUBJECT = "8f1c0e4e-0000-4000-8000-000000000001"
OWN = uuid.uuid4()
OTHER = uuid.uuid4()
BRANCH = uuid.uuid4()
WINDOW = {"from": DAY.isoformat(), "to": (DAY + timedelta(days=1)).isoformat()}


def headers(role: str, employee_id: uuid.UUID | str = "") -> dict[str, str]:
    return {
        identity.HEADER_SUBJECT: SUBJECT,
        identity.HEADER_ROLES: role,
        identity.HEADER_EMPLOYEE: str(employee_id),
    }


@pytest.fixture
async def facts(session) -> None:
    for employee in (OWN, OTHER):
        await domain.record_appointment_created(
            session,
            appointment_id=uuid.uuid4(),
            branch_id=BRANCH,
            employee_id=employee,
            client_id=uuid.uuid4(),
            service_id=uuid.uuid4(),
            starts_at=DAY + timedelta(hours=10),
            ends_at=DAY + timedelta(hours=11),
            created_at=DAY,
        )
    await session.commit()


class TestWorkload:
    async def test_specialist_sees_own(self, api, facts) -> None:
        response = await api.get(
            f"/employees/{OWN}/workload", params=WINDOW, headers=headers("specialist", OWN)
        )
        assert response.status_code == 200
        assert response.json()["employee_id"] == str(OWN)

    async def test_specialist_denied_foreign(self, api, facts) -> None:
        response = await api.get(
            f"/employees/{OTHER}/workload", params=WINDOW, headers=headers("specialist", OWN)
        )
        assert response.status_code == 403

    @pytest.mark.parametrize("role", ["admin", "manager"])
    async def test_privileged_sees_any(self, api, facts, role) -> None:
        response = await api.get(
            f"/employees/{OTHER}/workload", params=WINDOW, headers=headers(role)
        )
        assert response.status_code == 200

    async def test_account_without_employee_denied(self, api, facts) -> None:
        response = await api.get(
            f"/employees/{OTHER}/workload", params=WINDOW, headers=headers("specialist")
        )
        assert response.status_code == 403

    async def test_branch_reports_untouched_by_the_check(self, api, facts) -> None:
        """Отчёты филиала закрыты ролью, владение там ни при чём.

        Взята воронка, а не выручка: выручке нужен справочник филиалов из
        ядра, и тест проверял бы доступность соседа, а не разграничение.
        """
        response = await api.get(
            f"/branches/{BRANCH}/funnel", params=WINDOW, headers=headers("manager")
        )
        assert response.status_code == 200
