from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from keyholder.api.dependencies import DB, admin
from keyholder.models import ApplicationData, Backend, Customer, CustomerMapping, now
from keyholder.schemas import (
    CustomerCreate,
    CustomerUpdate,
    CustomerView,
    ECHSettings,
    MappingInput,
    TokenResult,
)
from keyholder.security import generate_token, hash_token

router = APIRouter(prefix="/admin", dependencies=[Depends(admin)])


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
    token = generate_token()
    customer = Customer(
        name=body.name, token_hash=hash_token(token), policy=body.policy.model_dump()
    )
    customer.mapping = CustomerMapping(
        backend_id=body.backend_id, upstream_username=body.upstream_username
    )
    db.add(customer)
    db.commit()
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


@router.get("/customers/{customer_id}", response_model=CustomerView)
def retrieve(customer_id: str, db: DB) -> Customer:
    return find(db, customer_id)


@router.patch("/customers/{customer_id}", response_model=CustomerView)
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


@router.put("/customers/{customer_id}/mapping", response_model=CustomerView)
def mapping(customer_id: str, body: MappingInput, db: DB) -> Customer:
    customer = find(db, customer_id)
    if customer.status == "revoked":
        raise HTTPException(409, "Revoked customers are terminal")
    if not db.get(Backend, body.backend_id):
        raise HTTPException(422, "Unknown backend")
    customer.mapping.backend_id = body.backend_id
    customer.mapping.upstream_username = body.upstream_username
    customer.updated_at = now()
    db.commit()
    return customer


@router.post("/customers/{customer_id}/rotate-token", response_model=TokenResult)
def rotate(customer_id: str, request: Request, db: DB) -> TokenResult:
    customer = find(db, customer_id)
    if customer.status == "revoked":
        raise HTTPException(409, "Revoked customers are terminal")
    token = generate_token()
    customer.token_hash = hash_token(token)
    customer.updated_at = now()
    db.commit()
    return token_result(request, customer, token)


@router.get("/settings/ech", response_model=ECHSettings)
def read_ech(db: DB) -> ECHSettings:
    row = db.get(ApplicationData, "ech")
    return ECHSettings.model_validate(row.value if row else {"ech_config_list": ""})


@router.put("/settings/ech", response_model=ECHSettings)
def write_ech(body: ECHSettings, db: DB) -> ECHSettings:
    row = db.get(ApplicationData, "ech")
    if row:
        row.value = body.model_dump()
    else:
        db.add(ApplicationData(key="ech", value=body.model_dump()))
    db.commit()
    return body
