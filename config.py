import os
from dotenv import load_dotenv

load_dotenv()

GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]
GCP_REGION = os.getenv("GCP_REGION", "us-central1")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-005")
BQ_DATASET = os.getenv("BQ_DATASET", "groundswell")
FIRESTORE_DB = os.getenv("FIRESTORE_DB", "groundswell-db")
MODEL_ARMOR_TEMPLATE = os.getenv("MODEL_ARMOR_TEMPLATE", "gs-armor")
MODEL_ARMOR_ENDPOINT = os.getenv(
    "MODEL_ARMOR_ENDPOINT",
    f"https://modelarmor.{GCP_REGION}.rep.googleapis.com/v1",
)
MCP_SERVICE_URL = os.getenv("MCP_SERVICE_URL", "http://localhost:8001")
INVENTORY_A2A_URL = os.getenv("INVENTORY_A2A_URL", "http://localhost:8002")
AP2_MERCHANT_PRIVATE_KEY = os.getenv("AP2_MERCHANT_PRIVATE_KEY", "")
AP2_MERCHANT_PUBLIC_KEY = os.getenv("AP2_MERCHANT_PUBLIC_KEY", "")
APP_ENV = os.getenv("APP_ENV", "development")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
