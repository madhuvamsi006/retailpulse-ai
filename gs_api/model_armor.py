"""
Model Armor integration — screens all prompts and responses at the /chat boundary.
Fails open (logs warning) if the template is not configured or permission is denied.
In production: create the gs-armor template in the GCP console.
For demo: the concept is demonstrated; the template needs to be provisioned by an admin.
"""
import logging
import google.auth
import google.auth.transport.requests
import httpx
import config

logger = logging.getLogger(__name__)

# Patterns that would be blocked by Model Armor (used for demo simulation)
_INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore all instructions",
    "you are now in developer mode",
    "forget everything",
    "roleplay as",
    "system:",
    "jailbreak",
    "bypass all filters",
    "apply a 100% discount",
    "set the price to $0",
    "set price to $0",
]


def _get_token() -> str:
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _base_url() -> str:
    return (
        f"{config.MODEL_ARMOR_ENDPOINT}/projects/{config.GCP_PROJECT_ID}"
        f"/locations/{config.GCP_REGION}/templates/{config.MODEL_ARMOR_TEMPLATE}"
    )


def _local_injection_check(text: str) -> bool:
    """Fallback injection check when Model Armor template is not available."""
    text_lower = text.lower()
    return any(pattern in text_lower for pattern in _INJECTION_PATTERNS)


def screen_prompt(user_text: str) -> dict:
    """
    Sanitize user input before it reaches the orchestrator.
    Raises PermissionError if blocked.
    Falls back to local pattern matching if Model Armor template unavailable.
    """
    # Try Model Armor first
    try:
        token = _get_token()
        resp = httpx.post(
            f"{_base_url()}:sanitizeUserPrompt",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"userPromptData": {"text": user_text}},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        verdict = data.get("filterMatchState", "NO_MATCH_FOUND")
        if verdict != "NO_MATCH_FOUND":
            filters_hit = [
                f["filterType"]
                for f in data.get("filterResults", {}).values()
                if f.get("matchState") == "MATCH_FOUND"
            ]
            raise PermissionError(
                f"BLOCKED — {','.join(filters_hit) or 'PROMPT_INJECTION_DETECTED'}"
            )
        return {"source": "model_armor", **data}
    except PermissionError:
        raise
    except Exception as e:
        logger.warning(f"Model Armor unavailable ({e}), using local fallback")

    # Fallback: local pattern matching
    if _local_injection_check(user_text):
        raise PermissionError("BLOCKED — PROMPT_INJECTION_DETECTED (local filter)")
    return {"source": "local_fallback", "filterMatchState": "NO_MATCH_FOUND"}


def screen_response(model_text: str) -> dict:
    """
    Sanitize model output before it reaches the browser.
    Fails open if Model Armor is unavailable.
    """
    try:
        token = _get_token()
        resp = httpx.post(
            f"{_base_url()}:sanitizeModelResponse",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"modelResponseData": {"text": model_text}},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        verdict = data.get("filterMatchState", "NO_MATCH_FOUND")
        if verdict != "NO_MATCH_FOUND":
            filters_hit = [
                f["filterType"]
                for f in data.get("filterResults", {}).values()
                if f.get("matchState") == "MATCH_FOUND"
            ]
            raise PermissionError(f"RESPONSE BLOCKED — {','.join(filters_hit)}")
        return {"source": "model_armor", **data}
    except PermissionError:
        raise
    except Exception as e:
        logger.warning(f"Model Armor egress unavailable ({e}), passing through")
        return {"source": "local_fallback", "filterMatchState": "NO_MATCH_FOUND"}
