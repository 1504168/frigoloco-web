"""Client CRUD plus fees and interventions sub-resources."""

from __future__ import annotations

from fastapi import Depends, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.master import Client, ClientFee, ClientIntervention, Fridge
from app.schemas.masters import (
    ClientCreate,
    ClientFeeCreate,
    ClientFeeRead,
    ClientInterventionCreate,
    ClientInterventionRead,
    ClientRead,
    ClientUpdate,
    Page,
    PaginationParams,
    api_error,
    make_router,
    pagination,
)

router = make_router(prefix="/api/v1/clients", tags=["clients"])


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


# --- Interventions ---------------------------------------------------------


@router.get("/{client_id}/interventions", response_model=list[ClientInterventionRead])
def list_client_interventions(
    client_id: int, session: Session = Depends(get_db)
) -> list[ClientInterventionRead]:
    _get_or_404(client_id, session)
    rows = list(
        session.execute(
            select(ClientIntervention)
            .join(Fridge, Fridge.id == ClientIntervention.fridge_id)
            .where(Fridge.client_id == client_id)
            .order_by(ClientIntervention.occurred_at.desc())
        )
        .scalars()
        .all()
    )
    return [ClientInterventionRead.model_validate(row) for row in rows]


@router.post(
    "/{client_id}/interventions",
    response_model=ClientInterventionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_client_intervention(
    client_id: int,
    body: ClientInterventionCreate,
    session: Session = Depends(get_db),
) -> ClientInterventionRead:
    _get_or_404(client_id, session)
    fridge = session.get(Fridge, body.fridge_id)
    if fridge is None or fridge.client_id != client_id:
        raise api_error(
            422,
            "validation_error",
            "Fridge does not belong to this client",
            {"fridge_id": body.fridge_id, "client_id": client_id},
        )
    intervention = ClientIntervention(**body.model_dump())
    session.add(intervention)
    session.commit()
    session.refresh(intervention)
    return ClientInterventionRead.model_validate(intervention)
