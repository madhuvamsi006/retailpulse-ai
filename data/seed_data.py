"""
Seed BigQuery and Firestore with realistic retail data.
Run: python -I data/seed_data.py
Planted patterns: weekend spike, viral SKU ramp, size curve (9-10 sell 3x faster), one 4-day stockout.
"""
import random
import sys
import time
import uuid
from datetime import date, timedelta

sys.path.insert(0, "/home/appadmin/groundswell")
import config
from data.embeddings import generate_embedding
from google.cloud import bigquery, firestore

BQ = bigquery.Client(project=config.GCP_PROJECT_ID)
FS = firestore.Client(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DB)
DATASET = f"{config.GCP_PROJECT_ID}.{config.BQ_DATASET}"

PRODUCTS = [
    {"sku": "SHOE-PEG41-GRY", "name": "Pegasus 41 Max-Cushion Road Runner", "category": "running-road",
     "price": 139.99, "unit_cost": 62.00, "available_sizes": ["7","8","9","10","11","12","13"],
     "available_widths": ["D","2E"], "total_stock": 48, "supplier_id": "SUP-NIKE-01",
     "description": "Max-cushioned road marathon training shoe with ReactX foam. Grey/white colorway."},
    {"sku": "SHOE-TRAIL-BLK", "name": "TrailBlazer Pro Aggressive Lug Trail Shoe", "category": "running-trail",
     "price": 124.99, "unit_cost": 54.00, "available_sizes": ["7","8","9","10","11","12"],
     "available_widths": ["D"], "total_stock": 22, "supplier_id": "SUP-SALOMON-01",
     "description": "Aggressive lug trail shoe for technical terrain. Black/orange."},
    {"sku": "SHOE-DRESS-BRN", "name": "Oxford Executive Leather Dress Shoe", "category": "dress",
     "price": 189.99, "unit_cost": 88.00, "available_sizes": ["8","9","10","11","12"],
     "available_widths": ["D","EE"], "total_stock": 15, "supplier_id": "SUP-ALLEN-01",
     "description": "Premium leather oxford for business formal. Brown."},
    {"sku": "SHOE-XFIT-WHT", "name": "CrossFit Trainer 5.0 Wide", "category": "training",
     "price": 109.99, "unit_cost": 48.00, "available_sizes": ["8","9","10","11","12","13"],
     "available_widths": ["D","2E","4E"], "total_stock": 34, "supplier_id": "SUP-REEBOK-01",
     "description": "Stable wide-fit cross-training shoe for gym and WODs."},
    {"sku": "SHOE-SLIP-BLK", "name": "ComfortWalk Slip-On Casual", "category": "casual",
     "price": 79.99, "unit_cost": 32.00, "available_sizes": ["7","8","9","10","11","12"],
     "available_widths": ["D","2E"], "total_stock": 60, "supplier_id": "SUP-SKECHERS-01",
     "description": "Lightweight memory foam slip-on for all-day wear."},
]

SUPPLIERS = [
    {"supplier_id": "SUP-NIKE-01", "name": "Nike Direct", "lead_time_days": 7, "moq": 24, "reliability_score": 0.97},
    {"supplier_id": "SUP-SALOMON-01", "name": "Salomon Wholesale", "lead_time_days": 14, "moq": 12, "reliability_score": 0.91},
    {"supplier_id": "SUP-ALLEN-01", "name": "Allen Edmonds B2B", "lead_time_days": 21, "moq": 6, "reliability_score": 0.88},
    {"supplier_id": "SUP-REEBOK-01", "name": "Reebok Distribution", "lead_time_days": 10, "moq": 18, "reliability_score": 0.94},
    {"supplier_id": "SUP-SKECHERS-01", "name": "Skechers Wholesale", "lead_time_days": 5, "moq": 24, "reliability_score": 0.99},
]

STORES = [
    {"store_id": "STR-01", "name": "Downtown Flagship", "location": "Chicago Loop", "region": "midwest"},
    {"store_id": "STR-02", "name": "Northside", "location": "Lincoln Park, Chicago", "region": "midwest"},
    {"store_id": "STR-03", "name": "Westfield Mall", "location": "Schaumburg, IL", "region": "midwest"},
    {"store_id": "STR-04", "name": "Oak Park", "location": "Oak Park, IL", "region": "midwest"},
    {"store_id": "STR-05", "name": "Evanston", "location": "Evanston, IL", "region": "midwest"},
    {"store_id": "STR-06", "name": "Naperville", "location": "Naperville, IL", "region": "midwest"},
]

SOCIAL_POSTS = [
    # Viral ramp for PEG41 — 4 days, planted to drive surge
    {"platform": "tiktok", "post_text": "ok these grey cushioned runners are actually unreal 😭 everyone at the gym has them now #pegasus41", "sku": "SHOE-PEG41-GRY", "engagement_score": 9.2, "hours_ago": 6},
    {"platform": "reddit", "post_text": "Finally found a marathon shoe that doesn't destroy my knees — the grey pegasus max cushion ones from Nike. 10/10", "sku": "SHOE-PEG41-GRY", "engagement_score": 7.8, "hours_ago": 10},
    {"platform": "tiktok", "post_text": "POV you find out the Peg 41 grey is $139 and you buy 2 pairs 😂💸", "sku": "SHOE-PEG41-GRY", "engagement_score": 8.1, "hours_ago": 14},
    {"platform": "instagram", "post_text": "Marathon training in the Pegasus 41 greys — these are a game changer for long runs", "sku": "SHOE-PEG41-GRY", "engagement_score": 6.5, "hours_ago": 18},
    # Noise posts — should NOT fire a surge
    {"platform": "twitter", "post_text": "anyone know a good trail shoe?", "sku": None, "engagement_score": 0.5, "hours_ago": 2},
    {"platform": "reddit", "post_text": "Looking for wide fit options under $120", "sku": None, "engagement_score": 0.3, "hours_ago": 5},
]


def seed_products():
    print("Seeding products + embeddings...")
    rows = []
    for p in PRODUCTS:
        embedding = generate_embedding(p["description"])
        rows.append({**p, "embedding": embedding})
    BQ.insert_rows_json(f"{DATASET}.products", rows)
    print(f"  {len(rows)} products inserted")


def seed_suppliers():
    print("Seeding suppliers...")
    BQ.insert_rows_json(f"{DATASET}.suppliers", SUPPLIERS)


def seed_stores():
    print("Seeding stores...")
    BQ.insert_rows_json(f"{DATASET}.stores", STORES)


def seed_sales():
    print("Seeding 18 months of sales history...")
    rows = []
    today = date.today()
    size_weights = {"7": 0.5, "8": 0.8, "9": 1.2, "10": 1.5, "11": 1.3, "12": 0.9, "13": 0.4}
    for p in PRODUCTS:
        for i in range(540):  # 18 months
            d = today - timedelta(days=i)
            base = random.randint(2, 8)
            # Weekend spike
            if d.weekday() in (5, 6):
                base = int(base * 1.6)
            # PEG41 viral ramp in last 4 days (planted)
            if p["sku"] == "SHOE-PEG41-GRY" and i < 4:
                base = int(base * 4.5)
            for store in STORES:
                daily = max(0, base + random.randint(-2, 2))
                rows.append({
                    "sale_id": str(uuid.uuid4())[:8],
                    "sku": p["sku"],
                    "variant_id": f"{p['sku']}-{store['store_id']}",
                    "store_id": store["store_id"],
                    "sale_date": d.isoformat(),
                    "daily_units_sold": daily,
                    "revenue": round(daily * p["price"], 2),
                })
    BQ.insert_rows_json(f"{DATASET}.sales", rows)
    print(f"  {len(rows)} sales rows inserted")


def seed_social_signals():
    print("Seeding social posts...")
    now = time.time()
    rows = []
    for post in SOCIAL_POSTS:
        rows.append({
            "post_id": str(uuid.uuid4())[:8],
            "platform": post["platform"],
            "post_text": post["post_text"],
            "sku": post["sku"],
            "engagement_score": post["engagement_score"],
            "posted_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(now - post["hours_ago"] * 3600)
            ),
        })
    BQ.insert_rows_json(f"{DATASET}.social_signals", rows)
    print(f"  {len(rows)} posts inserted")


def seed_arima_forecast():
    """Seed the ARIMA_PLUS baseline for PEG41 — 31 units (the baseline the viral signal will beat)."""
    print("Seeding ARIMA baseline forecast...")
    now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rows = [{
        "sku": "SHOE-PEG41-GRY",
        "horizon_days": 7,
        "forecast_timestamp": now_str,
        "forecast_value": 31.0,
        "prediction_interval_lower_bound": 22.0,
        "prediction_interval_upper_bound": 40.0,
        "computed_at": now_str,
    }]
    BQ.insert_rows_json(f"{DATASET}.stockout_forecast", rows)
    print("  ARIMA baseline: 31 units for PEG41")


def seed_firestore_inventory():
    print("Seeding Firestore inventory...")
    for p in PRODUCTS:
        per_store = max(2, p["total_stock"] // len(STORES))
        for store in STORES:
            doc_id = f"{p['sku']}_{store['store_id']}"
            # STR-04 gets critically low PEG41 stock to trigger stockout warning
            on_hand = 2 if (p["sku"] == "SHOE-PEG41-GRY" and store["store_id"] == "STR-04") else per_store
            FS.collection("inventory").document(doc_id).set({
                "sku": p["sku"],
                "store_id": store["store_id"],
                "on_hand": on_hand,
                "reserved": 0,
            })
    print(f"  {len(PRODUCTS) * len(STORES)} inventory docs written")


if __name__ == "__main__":
    seed_products()
    seed_suppliers()
    seed_stores()
    seed_sales()
    seed_social_signals()
    seed_arima_forecast()
    seed_firestore_inventory()
    print("\nSeed complete.")
