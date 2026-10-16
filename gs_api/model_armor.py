"""Model Armor integration — screens all prompts and responses at the /chat boundary."""
import google.auth
import google.auth.transport.requests
import httpx
import config


def _get_token() -> str:
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _base_url() -> str:
    return (
        f"{config.MODEL_ARMOR_ENDPOINT}/projects/{config.GCP_PROJECT_ID}"
        f"/locations/{config.GCP_REGION}/templates/{config.MODEL_ARMOR_TEMPLATE}"
    )


def screen_prompt(user_text: str) -> dict:
    """
    Sanitize user input before it reaches the orchestrator.
    Raises PermissionError if blocked.
    """
    token = _get_token()
    resp = httpx.post(
        f"{_base_url()}:sanitizeUserPrompt",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"userPromptData": {"text": user_text}},
        timeout=10,
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
    return data


def screen_response(model_text: str) -> dict:
    """Sanitize model output before it reaches the browser."""
    token = _get_token()
    resp = httpx.post(
        f"{_base_url()}:sanitizeModelResponse",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"modelResponseData": {"text": model_text}},
        timeout=10,
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
            f"RESPONSE BLOCKED — {','.join(filters_hit)}"
        )
    return data
