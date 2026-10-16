"""Generate text embeddings via Vertex AI text-embedding-005."""
import functools
import google.auth
import google.auth.transport.requests
import httpx
import config


@functools.lru_cache(maxsize=512)
def generate_embedding(text: str) -> list[float]:
    """Generate a text embedding. Cached to avoid redundant API calls."""
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())

    endpoint = (
        f"https://{config.GCP_REGION}-aiplatform.googleapis.com/v1"
        f"/projects/{config.GCP_PROJECT_ID}/locations/{config.GCP_REGION}"
        f"/publishers/google/models/{config.EMBEDDING_MODEL}:predict"
    )
    resp = httpx.post(
        endpoint,
        headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"},
        json={"instances": [{"content": text}]},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["predictions"][0]["embeddings"]["values"]
