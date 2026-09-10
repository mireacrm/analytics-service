"""Расчёт конверсии воронки."""

import pytest

from app.domain import Funnel


@pytest.mark.parametrize(
    ("completed", "cancelled", "expected"),
    [
        (8, 2, 0.8),
        (0, 5, 0.0),
        (5, 0, 1.0),
        (1, 3, 0.25),
    ],
)
def test_conversion(completed: int, cancelled: int, expected: float):
    funnel = Funnel(
        created=completed + cancelled, completed=completed, cancelled=cancelled, pending=0
    )

    assert funnel.conversion == expected


def test_pending_excluded_from_conversion():
    """Ещё не состоявшиеся записи конверсию не портят: исход неизвестен."""
    funnel = Funnel(created=12, completed=8, cancelled=2, pending=2)

    assert funnel.conversion == 0.8


def test_conversion_without_resolved_is_zero():
    funnel = Funnel(created=3, completed=0, cancelled=0, pending=3)

    assert funnel.conversion == 0.0
