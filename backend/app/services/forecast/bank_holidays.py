"""Bank holidays: public holidays the forecast does not count as selling days."""

from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.planning import BankHoliday
from app.schemas.masters import api_error
from app.services.stock_service import record_audit


def list_bank_holidays(year: int | None, session: Session) -> list[BankHoliday]:
    """Every bank holiday (of ``year`` when given), oldest first."""
    stmt = select(BankHoliday).order_by(BankHoliday.holiday_date)
    if year is not None:
        stmt = stmt.where(
            BankHoliday.holiday_date >= datetime.date(year, 1, 1),
            BankHoliday.holiday_date <= datetime.date(year, 12, 31),
        )
    return list(session.execute(stmt).scalars().all())


def load_bank_holiday_labels(
    first_day: datetime.date,
    last_day: datetime.date,
    session: Session,
) -> dict[datetime.date, str]:
    """Holiday label per date, for the dates from ``first_day`` to ``last_day`` inclusive."""
    rows = session.execute(
        select(BankHoliday.holiday_date, BankHoliday.label).where(
            BankHoliday.holiday_date >= first_day,
            BankHoliday.holiday_date <= last_day,
        )
    ).all()
    return {row.holiday_date: row.label for row in rows}


def create_bank_holiday(
    *,
    holiday_date: datetime.date,
    label: str,
    user_id: int | None,
    session: Session,
) -> BankHoliday:
    if session.get(BankHoliday, holiday_date) is not None:
        raise api_error(
            409,
            "exists",
            "This date is already a bank holiday",
            {"holiday_date": holiday_date.isoformat()},
        )
    holiday = BankHoliday(holiday_date=holiday_date, label=label)
    session.add(holiday)
    record_audit(
        session,
        action="bank_holiday.create",
        entity="bank_holidays",
        entity_id=holiday_date.isoformat(),
        after={"holiday_date": holiday_date.isoformat(), "label": label},
        user_id=user_id,
    )
    session.commit()
    return holiday


def delete_bank_holiday(
    *,
    holiday_date: datetime.date,
    user_id: int | None,
    session: Session,
) -> None:
    holiday = session.get(BankHoliday, holiday_date)
    if holiday is None:
        raise api_error(
            404,
            "not_found",
            "No bank holiday on this date",
            {"holiday_date": holiday_date.isoformat()},
        )
    record_audit(
        session,
        action="bank_holiday.delete",
        entity="bank_holidays",
        entity_id=holiday_date.isoformat(),
        before={"holiday_date": holiday_date.isoformat(), "label": holiday.label},
        user_id=user_id,
    )
    session.delete(holiday)
    session.commit()
