"""Settings endpoints: read all tunables and upsert one by key.

Values are stored as JSONB (scoring weights, margins, fees, thresholds), so the
typed ``value`` from the request is persisted verbatim.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.master import Setting
from app.schemas.alerts_settings import SettingRead, SettingUpdate
from app.services.orders_service import envelope, write_audit

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("", response_model=list[SettingRead])
@envelope
def list_settings(db: Session = Depends(get_db)) -> list[SettingRead]:
    rows = db.execute(select(Setting).order_by(Setting.key)).scalars().all()
    return [SettingRead.model_validate(row) for row in rows]


@router.put("/{key}", response_model=SettingRead)
@envelope
def upsert_setting(
    key: str,
    payload: SettingUpdate,
    db: Session = Depends(get_db),
) -> SettingRead:
    setting = db.get(Setting, key)
    before = {"value": setting.value} if setting else None
    if setting is None:
        setting = Setting(key=key, value=payload.value, description=payload.description)
        db.add(setting)
    else:
        setting.value = payload.value
        if payload.description is not None:
            setting.description = payload.description
        setting.updated_at = datetime.datetime.now(datetime.timezone.utc)

    write_audit(
        db,
        action="upsert",
        entity="setting",
        entity_id=key,
        before=before,
        after={"value": payload.value},
    )
    db.commit()
    db.refresh(setting)
    return SettingRead.model_validate(setting)
