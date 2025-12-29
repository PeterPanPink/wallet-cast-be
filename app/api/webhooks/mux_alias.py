"""Alias endpoint for Mux webhook at /api/v1/live/webhooks/mux.

This provides a versioned API path that forwards to the main webhook handler.
"""

from fastapi import APIRouter, Header, Request

from app.api.webhooks.mux import MuxWebhookSuccess, mux_webhook
from app.shared.api.utils import ApiFailure

router = APIRouter(prefix="/live/webhooks", tags=["Webhooks"])


@router.post("/mux", response_model=MuxWebhookSuccess | ApiFailure)
async def mux_webhook_alias(
    request: Request,
    mux_signature: str | None = Header(None, alias="mux-signature"),
) -> MuxWebhookSuccess | ApiFailure:
    """Alias endpoint for Mux webhook - forwards to main handler.

    This endpoint provides a versioned API path at /api/v1/live/webhooks/mux
    that forwards all requests to the main webhook handler.

    Args:
        request: FastAPI request object
        mux_signature: Signature header for verification

    Returns:
        Success response with handling results or failure
    """
    return await mux_webhook(request, mux_signature)
