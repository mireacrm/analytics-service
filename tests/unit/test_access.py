import uuid

import pytest
from mireacrm_common import identity
from mireacrm_common.errors import ForbiddenError

from app.infra import access

OWN = uuid.uuid4()
OTHER = uuid.uuid4()


def caller(*roles: str, employee_id: uuid.UUID | None = OWN) -> identity.Caller:
    return identity.Caller(
        subject="8f1c0e4e-0000-4000-8000-000000000001",
        roles=frozenset(roles),
        employee_id=str(employee_id) if employee_id else "",
    )


class TestAllowed:
    def test_own_object(self) -> None:
        access.ensure_owner(OWN, "визит", caller("specialist"))

    @pytest.mark.parametrize("role", ["admin", "manager"])
    def test_privileged_sees_others(self, role) -> None:
        access.ensure_owner(OTHER, "визит", caller(role, employee_id=None))

    def test_call_from_inside_the_system(self) -> None:
        """Потребитель события действует не от имени человека — ограничивать нечем."""
        access.ensure_owner(OTHER, "визит", identity.ANONYMOUS)


class TestDenied:
    def test_foreign_object(self) -> None:
        with pytest.raises(ForbiddenError):
            access.ensure_owner(OTHER, "визит", caller("specialist"))

    def test_account_without_employee(self) -> None:
        """Учётная запись без сотрудника не должна видеть ничего чужого."""
        with pytest.raises(ForbiddenError):
            access.ensure_owner(OTHER, "визит", caller("specialist", employee_id=None))

    def test_unknown_owner(self) -> None:
        with pytest.raises(ForbiddenError):
            access.ensure_owner(None, "визит", caller("specialist"))

    def test_uses_current_caller_when_not_given(self) -> None:
        identity.set_current(caller("specialist"))
        try:
            with pytest.raises(ForbiddenError):
                access.ensure_owner(OTHER, "визит")
        finally:
            identity.set_current(identity.ANONYMOUS)
