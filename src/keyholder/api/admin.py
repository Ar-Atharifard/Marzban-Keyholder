from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from keyholder.api.dependencies import DB, admin
from keyholder.models import Backend, Customer, CustomerMapping, Registration, now
from keyholder.schemas import (
    CustomerCreate,
    CustomerUpdate,
    CustomerView,
    ErrorResponse,
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
    if not db.get(Backend, body.backend_id):
        raise HTTPException(422, "Unknown backend")
    existing = db.get(Registration, (body.backend_id, body.upstream_username))
    if existing:
        customer = find(db, existing.customer_id)
        return retrieve_token(customer.id, request, db)
    token = generate_token()
    customer = Customer(
        name=body.name,
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
    if body.policy is not None:
        customer.policy = body.policy.model_dump()
    if body.status is not None:
        customer.status = body.status
        if body.status == "revoked":
            customer.revoked_at = now()
    customer.updated_at = now()
    db.commit()
    return customer


@router.put(
    "/customers/{customer_id}/mapping",
    response_model=CustomerView,
    responses={
        404: {"model": ErrorResponse, "description": "Customer not found"},
        409: {"model": ErrorResponse, "description": "Revoked customers are terminal"},
    },
)
def mapping(customer_id: str, body: MappingInput, db: DB) -> Customer:
    customer = find(db, customer_id)
    if customer.status == "revoked":
        raise HTTPException(409, "Revoked customers are terminal")
    if not db.get(Backend, body.backend_id):
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
