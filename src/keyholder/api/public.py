import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import select, text

from keyholder.api.dependencies import DB
from keyholder.backends.base import UpstreamError, UpstreamUnavailable
from keyholder.models import Customer
from keyholder.policies import stored_policy
from keyholder.rendering.profiles import allowed_cdn, apply_cdn_ech, generate_profiles
from keyholder.rendering.renderers import select_renderer
from keyholder.schemas import ErrorResponse, Policy
from keyholder.security import hash_token, valid_token, verify_token

router = APIRouter(
    responses={
        422: {"model": ErrorResponse, "description": "Invalid request"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    }
)


@router.get("/health")
def health(db: DB) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get(
    "/s/{token}",
    response_class=Response,
    responses={
        200: {
            "description": "Normalized subscription in the selected format",
            "content": {
                "text/plain": {"schema": {"type": "string", "description": "Base64 URI lines"}},
                "application/json": {"schema": {"type": "array", "items": {"type": "object"}}},
            },
        },
        404: {"model": ErrorResponse, "description": "Subscription not found or unavailable"},
        502: {"model": ErrorResponse, "description": "Upstream unavailable"},
        503: {
            "model": ErrorResponse,
            "description": "No compatible profiles or backend unavailable",
        },
    },
)
async def subscription(
    token: str,
    request: Request,
    db: DB,
    output: Annotated[Literal["uri", "xray"] | None, Query(alias="format")] = None,
) -> Response:
    if not valid_token(token):
        raise HTTPException(404, "Subscription not found")
    customer = db.scalar(select(Customer).where(Customer.token_hash == hash_token(token)))
    if not customer or not verify_token(token, customer.token_hash) or customer.status != "active":
        raise HTTPException(404, "Subscription not found")
    adapter = request.app.state.backends.get(customer.mapping.backend_id)
    if adapter is None:
        raise HTTPException(503, "Backend unavailable")
    username = customer.mapping.upstream_username
    policy = (
        {"profiles": list(request.app.state.settings.enabled_profiles)}
        if request.app.state.settings.profile_source in {"marzban", "upstream"}
        else stored_policy(customer.policy)
    )
    # Release the read transaction before waiting for Marzban. Otherwise slow
    # upstream requests hold pool connections and can stall unrelated requests.
    db.close()
    try:
        async with asyncio.timeout(request.app.state.settings.upstream_timeout):
            links = await adapter.configurations(username)
        settings = request.app.state.settings
        profiles = generate_profiles(
            links, Policy.model_validate(policy), settings.allowed_cdn_networks
        )
        profiles = [p for p in profiles if p.kind in settings.enabled_profiles]
        allowed_hosts = request.app.state.settings.allowed_cdn_hosts
        profiles = [
            p for p in profiles if allowed_cdn(p, allowed_hosts, settings.allowed_cdn_networks)
        ]
        profiles = apply_cdn_ech(
            profiles, settings.cdn_ech_config, allowed_hosts, settings.cdn_tls_compatibility
        )
        renderer = select_renderer(output, request.headers.get("user-agent", ""))
        content = renderer.render(profiles)
    except UpstreamUnavailable:
        raise HTTPException(404, "Subscription unavailable") from None
    except (UpstreamError, TimeoutError):
        raise HTTPException(502, "Upstream unavailable") from None
    except ValueError:
        raise HTTPException(503, "No compatible subscription profiles") from None
    return Response(content, media_type=renderer.media_type)
