"""Twilio inbound WhatsApp webhook.

Fast-ack + background task: Twilio expects a reply within ~15s, and a cart
change needs to reach both phones (one webhook response can't do that), so
the actual work happens off the request path.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Response

from app.conversation.service import ConversationService
from app.dependencies import get_conversation_service, get_verified_twilio_form

router = APIRouter()


@router.post("/webhook")
def whatsapp_webhook(
    background_tasks: BackgroundTasks,
    form: dict = Depends(get_verified_twilio_form),
    conversation: ConversationService = Depends(get_conversation_service),
) -> Response:
    sender = form.get("From", "").removeprefix("whatsapp:")
    body = form.get("Body", "")
    # Twilio sends the sender's WhatsApp display name on every inbound message.
    # Without it, attribution falls back to the phone number and the household
    # reads "added by +9198…" instead of a name (DB_DESIGN.md §1).
    profile_name = form.get("ProfileName") or None
    background_tasks.add_task(conversation.handle, sender, body, profile_name)
    # Twilio expects TwiML (XML) from a messaging webhook, not JSON — the
    # actual reply goes out separately via the REST API in the background
    # task above, so this is deliberately empty.
    return Response(content="<Response></Response>", media_type="application/xml")
