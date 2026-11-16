"""Client CRUD plus fees, contacts and rules sub-resources."""

from __future__ import annotations

import datetime

from fastapi import Depends, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.master import Client, ClientContact, ClientFee, ClientRule, Fridge
from app.schemas.masters import (
    ClientContactItem,
    ClientContactsReplace,
    ClientCreate,
    ClientFeeCreate,
    ClientFeeRead,
    ClientRead,
    ClientRuleCreate,
    ClientRuleRead,
    ClientRuleViolation,
    ClientUpdate,
    Page,
    PaginationParams,
    api_error,
    make_router,
    pagination,
)
from app.services.client_rules_service import find_rule_violations

router = make_router(prefix="/api/v1/clients", tags=["clients"])

CONTACT_DETAIL_FIELDS = ("name", "job_title", "phone", "email")


def _get_or_404(client_id: int, session: Session) -> Client:
    client = session.get(Client, client_id)
    if client is None:
        raise api_error(404, "not_found", "Client not found", {"id": client_id})
    return client


@router.get("", response_model=Page[ClientRead])
def list_clients(
    page: PaginationParams = Depends(pagination),
    session: Session = Depends(get_db),
) -> Page[ClientRead]:
    total = session.execute(select(func.count()).select_from(Client)).scalar_one()
    rows = list(
        session.execute(
            select(Client).order_by(Client.name).limit(page.limit).offset(page.offset)
        )
        .scalars()
        .all()
    )
    return Page(
        items=[ClientRead.model_validate(row) for row in rows],
        total=int(total),
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/rules/violations", response_model=list[ClientRuleViolation])
def list_client_rule_violations(
    product_ids: list[int] = Query(default=[]),
    fridge_ids: list[int] = Query(default=[]),
    on_date: datetime.date | None = Query(
        default=None, description="Date the rules must be valid on (default today)."
    ),
    session: Session = Depends(get_db),
) -> list[ClientRuleViolation]:
    """(fridge, product) pairs that break an exclude_tag rule. A warning, never a block."""
    rules_date = on_date or datetime.date.today()
    violations = find_rule_violations(session, product_ids, fridge_ids, rules_date)
    return [ClientRuleViolation.model_validate(violation) for violation in violations]


@router.post("", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
def create_client(body: ClientCreate, session: Session = Depends(get_db)) -> ClientRead:
    client = Client(**body.model_dump())
    session.add(client)
    session.commit()
    session.refresh(client)
    return ClientRead.model_validate(client)


@router.get("/{client_id}", response_model=ClientRead)
def get_client(client_id: int, session: Session = Depends(get_db)) -> ClientRead:
    return ClientRead.model_validate(_get_or_404(client_id, session))


@router.put("/{client_id}", response_model=ClientRead)
def update_client(
    client_id: int, body: ClientUpdate, session: Session = Depends(get_db)
) -> ClientRead:
    client = _get_or_404(client_id, session)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(client, field, value)
    session.commit()
    session.refresh(client)
    return ClientRead.model_validate(client)


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(client_id: int, session: Session = Depends(get_db)) -> None:
    client = _get_or_404(client_id, session)
    session.delete(client)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(
            409, "conflict", "Client is referenced and cannot be deleted", {"id": client_id}
        ) from exc


# --- Fees ------------------------------------------------------------------


@router.get("/{client_id}/fees", response_model=list[ClientFeeRead])
def list_client_fees(
    client_id: int, session: Session = Depends(get_db)
) -> list[ClientFeeRead]:
    _get_or_404(client_id, session)
    rows = list(
        session.execute(
            select(ClientFee)
            .where(ClientFee.client_id == client_id)
            .order_by(ClientFee.contract_start.desc())
        )
        .scalars()
        .all()
    )
    return [ClientFeeRead.model_validate(row) for row in rows]


@router.post(
    "/{client_id}/fees",
    response_model=ClientFeeRead,
    status_code=status.HTTP_201_CREATED,
)
def create_client_fee(
    client_id: int, body: ClientFeeCreate, session: Session = Depends(get_db)
) -> ClientFeeRead:
    _get_or_404(client_id, session)
    fee = ClientFee(client_id=client_id, **body.model_dump())
    session.add(fee)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise api_error(
            422, "validation_error", "Invalid fee contract range", None
        ) from exc
    session.refresh(fee)
    return ClientFeeRead.model_validate(fee)


@router.get("/{client_id}/contacts", response_model=list[ClientContactItem])
def list_client_contacts(
    client_id: int, session: Session = Depends(get_db)
) -> list[ClientContactItem]:
    _get_or_404(client_id, session)
    rows = session.execute(
        select(ClientContact)
        .where(ClientContact.client_id == client_id)
        .order_by(ClientContact.role)
    ).scalars()
    return [ClientContactItem.model_validate(row) for row in rows]


@router.put("/{client_id}/contacts", response_model=list[ClientContactItem])
def replace_client_contacts(
    client_id: int,
    body: ClientContactsReplace,
    session: Session = Depends(get_db),
) -> list[ClientContactItem]:
    """Replace all contacts of a client; roles left out or sent empty are removed."""
    _get_or_404(client_id, session)
    roles = [item.role for item in body.items]
    if len(roles) != len(set(roles)):
        raise api_error(422, "validation_error", "Duplicate role in client contacts", None)
    session.execute(delete(ClientContact).where(ClientContact.client_id == client_id))
    for item in body.items:
        contact_fields = _cleaned_contact_fields(item)
        has_details = any(contact_fields[field] for field in CONTACT_DETAIL_FIELDS)
        if has_details:
            session.add(ClientContact(client_id=client_id, **contact_fields))
    session.commit()
    return list_client_contacts(client_id, session)


@router.get("/{client_id}/rules", response_model=list[ClientRuleRead])
def list_client_rules(
    client_id: int, session: Session = Depends(get_db)
) -> list[ClientRuleRead]:
    _get_or_404(client_id, session)
    rules = session.execute(
        select(ClientRule)
        .where(ClientRule.client_id == client_id)
        .order_by(ClientRule.fridge_id.nulls_first(), ClientRule.id)
    ).scalars()
    return [ClientRuleRead.model_validate(rule) for rule in rules]


@router.post(
    "/{client_id}/rules",
    response_model=ClientRuleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_client_rule(
    client_id: int,
    body: ClientRuleCreate,
    session: Session = Depends(get_db),
) -> ClientRuleRead:
    _get_or_404(client_id, session)
    if body.fridge_id is not None:
        _ensure_fridge_belongs_to_client(session, body.fridge_id, client_id)
    rule = ClientRule(client_id=client_id, **body.model_dump())
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return ClientRuleRead.model_validate(rule)


@router.delete("/{client_id}/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client_rule(
    client_id: int,
    rule_id: int,
    session: Session = Depends(get_db),
) -> None:
    rule = session.get(ClientRule, rule_id)
    if rule is None or rule.client_id != client_id:
        raise api_error(404, "not_found", "Client rule not found", {"id": rule_id})
    session.delete(rule)
    session.commit()


def _ensure_fridge_belongs_to_client(session: Session, fridge_id: int, client_id: int) -> None:
    fridge = session.get(Fridge, fridge_id)
    if fridge is None or fridge.client_id != client_id:
        raise api_error(
            422,
            "validation_error",
            "The fridge does not belong to this client",
            {"fridge_id": fridge_id},
        )


def _cleaned_contact_fields(item: ClientContactItem) -> dict:
    """Contact fields with surrounding spaces removed and blank text stored as NULL."""
    cleaned = item.model_dump()
    for field in CONTACT_DETAIL_FIELDS:
        cleaned[field] = _blank_to_none(cleaned[field])
    return cleaned


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None
