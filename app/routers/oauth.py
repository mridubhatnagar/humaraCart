"""Instamart OAuth redirect callback — GET, hit by the holder's own browser
after they authorize (not a WhatsApp message)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.dependencies import get_onboarding_service
from app.onboarding.service import OnboardingService

router = APIRouter()


@router.get("/oauth/callback", response_class=HTMLResponse)
def oauth_callback(
    code: str,
    state: str,
    onboarding: OnboardingService = Depends(get_onboarding_service),
) -> str:
    onboarding.complete_holder_oauth(code, state)
    return "<h2>Instamart linked. Return to WhatsApp.</h2>"
