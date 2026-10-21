from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from keyholder.api.dependencies import DB, admin
from keyholder.backends.registry import backend_configs
from keyholder.models import ApplicationData, Backend, Customer, CustomerMapping, Registration, now
from keyholder.schemas import (
    BackendView,
    CustomerCreate,
    CustomerUpdate,
    CustomerView,
    ErrorResponse,
    InboundDefaults,
    InboundDefaultsView,
    MappingInput,
    TokenResult,
)
from keyholder.security import generate_token, hash_token
from keyholder.vault import decrypt, encrypt

router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(admin)],
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        422: {"model": ErrorResponse, "description": "Invalid request or unknown backend"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)


@router.get("/backends", response_model=list[BackendView])
def backends(request: Request, db: DB) -> list[BackendView]:
    return [
        BackendView(
            id=c.id,
            provider=c.provider,
            config_ref=c.config_ref,
            registered=db.get(Backend, c.id) is not None,
        )
        for c in backend_configs(request.app.state.settings)
    ]


@router.get("/backends/{backend_id}/inbound-defaults", response_model=InboundDefaultsView)
def inbound_defaults(backend_id: str, request: Request, db: DB) -> InboundDefaultsView:
    if not any(
        b.id == backend_id and b.provider == "marzban"
        for b in backend_configs(request.app.state.settings)
    ):
        raise HTTPException(404, "Marzban backend not configured")
    row = db.get(ApplicationData, "inbounds/" + sha256(backend_id.encode()).hexdigest()[:40])
    return InboundDefaultsView(
        backend_id=backend_id,
        inbound_tags=row.value["inbound_tags"]
        if row
        else list(request.app.state.settings.default_inbound_tags),
        source="database" if row else "environment",
    )


@router.put("/backends/{backend_id}/inbound-defaults", response_model=InboundDefaultsView)
def set_inbound_defaults(
    backend_id: str, body: InboundDefaults, request: Request, db: DB
) -> InboundDefaultsView:
    inbound_defaults(backend_id, request, db)
    key = "inbounds/" + sha256(backend_id.encode()).hexdigest()[:40]
    row = db.get(ApplicationData, key)
    if row is None:
        db.add(ApplicationData(key=key, value=body.model_dump()))
    else:
        row.value = body.model_dump()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Default selection changed concurrently; retry") from None
    return inbound_defaults(backend_id, request, db)


@router.post(
    "/backends/register",
    response_model=list[BackendView],
    responses={
        409: {"model": ErrorResponse, "description": "Backend registration conflict"},
    },
)
def register_backends(request: Request, db: DB) -> list[BackendView]:
    configs = backend_configs(request.app.state.settings)
    for c in configs:
        row = db.get(Backend, c.id)
        if row and (row.provider != c.provider or row.config_ref != c.config_ref):
            raise HTTPException(409, "Existing backend identity differs; use a new backend ID")
    for c in configs:
        if db.get(Backend, c.id) is None:
            db.add(Backend(id=c.id, provider=c.provider, config_ref=c.config_ref))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # A concurrent registration may win; verify its metadata before success.
        for c in configs:
            row = db.get(Backend, c.id)
            if not row or row.provider != c.provider or row.config_ref != c.config_ref:
                raise HTTPException(409, "Backend registration conflict") from None
    return backends(request, db)


def find(db: DB, customer_id: str) -> Customer:
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    return customer


def token_result(request: Request, customer: Customer, token: str) -> TokenResult:
    return TokenResult(
        customer=CustomerView.model_validate(customer),
        token=token,
        subscription_url=f"{request.app.state.settings.public_base_url}/s/{token}",
    )


@router.post("/customers", response_model=TokenResult, status_code=201)
def create(body: CustomerCreate, request: Request, db: DB) -> TokenResult:
    if not db.get(Backend, body.backend_id) or body.backend_id not in request.app.state.backends:
        raise HTTPException(422, "Unknown backend")
    existing = db.get(Registration, (body.backend_id, body.upstream_username))
    if existing:
        customer = find(db, existing.customer_id)
        return retrieve_token(customer.id, request, db)
    token = generate_token()
    customer = Customer(
        name=body.name,
        telegram=body.telegram,
        phone=body.phone,
        token_hash=hash_token(token),
        token_encrypted=encrypt(request.app.state.settings, token),
        policy=body.policy.model_dump(),
    )
    customer.mapping = CustomerMapping(
        backend_id=body.backend_id, upstream_username=body.upstream_username
    )
    db.add(customer)
    try:
        db.flush()
        db.add(
            Registration(
                backend_id=body.backend_id,
                upstream_username=body.upstream_username,
                customer_id=customer.id,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(Registration, (body.backend_id, body.upstream_username))
        if existing is None:
            raise HTTPException(409, "Registration conflict") from None
        return retrieve_token(existing.customer_id, request, db)
    return token_result(request, customer, token)


@router.get("/customers", response_model=list[CustomerView])
def listing(
    db: DB, offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> list[Customer]:
    return list(
        db.scalars(
            select(Customer).order_by(Customer.created_at, Customer.id).offset(offset).limit(limit)
        )
    )


@router.get(
    "/customers/{customer_id}",
    response_model=CustomerView,
    responses={404: {"model": ErrorResponse, "description": "Customer not found"}},
)
def retrieve(customer_id: str, db: DB) -> Customer:
    return find(db, customer_id)


@router.patch(
    "/customers/{customer_id}",
    response_model=CustomerView,
    responses={
        404: {"model": ErrorResponse, "description": "Customer not found"},
        409: {"model": ErrorResponse, "description": "Revoked customers are terminal"},
    },
)
def update(customer_id: str, body: CustomerUpdate, db: DB) -> Customer:
    customer = find(db, customer_id)
    if customer.status == "revoked":
        raise HTTPException(409, "Revoked customers are terminal")
    if body.name is not None:
        customer.name = body.name
    if "telegram" in body.model_fields_set:
        customer.telegram = body.telegram
    if "phone" in body.model_fields_set:
        customer.phone = body.phone
    if body.policy is not None:
        customer.policy = body.policy.model_dump()
    if body.status is not None:
        customer.status = body.status
        if body.status == "revoked":
            customer.revoked_at = now()
    customer.updated_at = now()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Telegram or phone already registered") from None
    return customer


@router.put(
    "/customers/{customer_id}/mapping",
    response_model=CustomerView,
    responses={
        404: {"model": ErrorResponse, "description": "Customer not found"},
        409: {"model": ErrorResponse, "description": "Revoked customers are terminal"},
    },
)
def mapping(customer_id: str, body: MappingInput, db: DB, request: Request) -> Customer:
    customer = find(db, customer_id)
    if customer.status == "revoked":
        raise HTTPException(409, "Revoked customers are terminal")
    if not db.get(Backend, body.backend_id) or body.backend_id not in request.app.state.backends:
        raise HTTPException(422, "Unknown backend")
    existing = db.get(Registration, (body.backend_id, body.upstream_username))
    if existing and existing.customer_id != customer.id:
        raise HTTPException(409, "Upstream account already registered")
    registration = db.scalar(select(Registration).where(Registration.customer_id == customer.id))
    if registration:
        db.delete(registration)
        db.flush()
    db.add(
        Registration(
            backend_id=body.backend_id,
            upstream_username=body.upstream_username,
            customer_id=customer.id,
        )
    )
    customer.mapping.backend_id = body.backend_id
    customer.mapping.upstream_username = body.upstream_username
    customer.updated_at = now()
    db.commit()
    return customer


@router.post(
    "/customers/{customer_id}/rotate-token",
    response_model=TokenResult,
    responses={
        404: {"model": ErrorResponse, "description": "Customer not found"},
        409: {"model": ErrorResponse, "description": "Revoked customers are terminal"},
    },
)
def rotate(customer_id: str, request: Request, db: DB) -> TokenResult:
    customer = find(db, customer_id)
    if customer.status == "revoked":
        raise HTTPException(409, "Revoked customers are terminal")
    token = generate_token()
    customer.token_hash = hash_token(token)
    customer.token_encrypted = encrypt(request.app.state.settings, token)
    customer.updated_at = now()
    db.commit()
    return token_result(request, customer, token)


@router.get(
    "/customers/{customer_id}/subscription",
    response_model=TokenResult,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def retrieve_token(customer_id: str, request: Request, db: DB) -> TokenResult:
    customer = find(db, customer_id)
    if customer.status == "revoked":
        raise HTTPException(409, "Revoked customers are terminal")
    if customer.token_encrypted is None:
        raise HTTPException(409, "Legacy link requires explicit rotation")
    try:
        token = decrypt(request.app.state.settings, customer.token_encrypted, customer.token_hash)
    except ValueError:
        raise HTTPException(503, "Token vault unavailable; restore encryption key") from None
    return token_result(request, customer, token)
