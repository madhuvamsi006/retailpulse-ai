"""
Seed BigQuery and Firestore with realistic multi-retailer, multi-warehouse retail data.
Run: python3 data/seed_data.py

Architecture:
  2 retailers → 2 warehouses each → 6 stores each = 12 stores total
  Planted patterns: weekend spike, viral SKU ramp (PEG41), size curve (9-10 sell 3x faster),
  one 4-day stockout at STR-04, one slow-mover (SHOE-DRESS-BRN).
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

# ── Retailers ──────────────────────────────────────────────────────────────────
RETAILERS = [
    {"retailer_id": "RTL-STRIDE", "name": "Stride Athletic", "type": "specialty-chain", "region": "midwest"},
    {"retailer_id": "RTL-FORMFIT", "name": "FormFit Footwear", "type": "specialty-chain", "region": "southeast"},
]

# ── Warehouses (2 per retailer = 4 total) ─────────────────────────────────────
WAREHOUSES = [
    # Stride Athletic
    {"warehouse_id": "WH-STR-CHI", "retailer_id": "RTL-STRIDE", "name": "Stride Chicago DC",
     "location": "Chicago, IL", "region": "midwest", "capacity_units": 50000},
    {"warehouse_id": "WH-STR-DET", "retailer_id": "RTL-STRIDE", "name": "Stride Detroit DC",
     "location": "Detroit, MI", "region": "midwest", "capacity_units": 35000},
    # FormFit Footwear
    {"warehouse_id": "WH-FF-ATL", "retailer_id": "RTL-FORMFIT", "name": "FormFit Atlanta DC",
     "location": "Atlanta, GA", "region": "southeast", "capacity_units": 45000},
    {"warehouse_id": "WH-FF-MIA", "retailer_id": "RTL-FORMFIT", "name": "FormFit Miami DC",
     "location": "Miami, FL", "region": "southeast", "capacity_units": 30000},
]

# ── Stores (6 per retailer = 12 total) ────────────────────────────────────────
STORES = [
    # Stride Athletic — served by WH-STR-CHI (STR-01 to STR-04) and WH-STR-DET (STR-05, STR-06)
    {"store_id": "STR-01", "retailer_id": "RTL-STRIDE", "warehouse_id": "WH-STR-CHI",
     "name": "Stride Downtown Flagship", "location": "Chicago Loop, IL", "region": "midwest"},
    {"store_id": "STR-02", "retailer_id": "RTL-STRIDE", "warehouse_id": "WH-STR-CHI",
     "name": "Stride Lincoln Park", "location": "Lincoln Park, Chicago, IL", "region": "midwest"},
    {"store_id": "STR-03", "retailer_id": "RTL-STRIDE", "warehouse_id": "WH-STR-CHI",
     "name": "Stride Westfield Mall", "location": "Schaumburg, IL", "region": "midwest"},
    {"store_id": "STR-04", "retailer_id": "RTL-STRIDE", "warehouse_id": "WH-STR-CHI",
     "name": "Stride Oak Park", "location": "Oak Park, IL", "region": "midwest"},
    {"store_id": "STR-05", "retailer_id": "RTL-STRIDE", "warehouse_id": "WH-STR-DET",
     "name": "Stride Evanston", "location": "Evanston, IL", "region": "midwest"},
    {"store_id": "STR-06", "retailer_id": "RTL-STRIDE", "warehouse_id": "WH-STR-DET",
     "name": "Stride Naperville", "location": "Naperville, IL", "region": "midwest"},
    # FormFit Footwear — served by WH-FF-ATL (STR-07 to STR-10) and WH-FF-MIA (STR-11, STR-12)
    {"store_id": "STR-07", "retailer_id": "RTL-FORMFIT", "warehouse_id": "WH-FF-ATL",
     "name": "FormFit Buckhead", "location": "Atlanta, GA", "region": "southeast"},
    {"store_id": "STR-08", "retailer_id": "RTL-FORMFIT", "warehouse_id": "WH-FF-ATL",
     "name": "FormFit Midtown ATL", "location": "Midtown Atlanta, GA", "region": "southeast"},
    {"store_id": "STR-09", "retailer_id": "RTL-FORMFIT", "warehouse_id": "WH-FF-ATL",
     "name": "FormFit Perimeter Mall", "location": "Dunwoody, GA", "region": "southeast"},
    {"store_id": "STR-10", "retailer_id": "RTL-FORMFIT", "warehouse_id": "WH-FF-ATL",
     "name": "FormFit Decatur", "location": "Decatur, GA", "region": "southeast"},
    {"store_id": "STR-11", "retailer_id": "RTL-FORMFIT", "warehouse_id": "WH-FF-MIA",
     "name": "FormFit Brickell", "location": "Brickell, Miami, FL", "region": "southeast"},
    {"store_id": "STR-12", "retailer_id": "RTL-FORMFIT", "warehouse_id": "WH-FF-MIA",
     "name": "FormFit Coral Gables", "location": "Coral Gables, FL", "region": "southeast"},
]

PRODUCTS = [
    {"sku": "SHOE-PEG41-GRY", "retailer_id": "RTL-STRIDE", "name": "Pegasus 41 Max-Cushion Road Runner",
     "category": "running-road", "price": 139.99, "unit_cost": 62.00,
     "available_sizes": ["7","8","9","10","11","12","13"],
     "available_widths": ["D","2E"], "total_stock": 288,
     "supplier_id": "SUP-NIKE-01",
     "description": "Max-cushioned road marathon training shoe with ReactX foam. Grey/white colorway."},
    {"sku": "SHOE-TRAIL-BLK", "retailer_id": "RTL-STRIDE", "name": "TrailBlazer Pro Aggressive Lug Trail Shoe",
     "category": "running-trail", "price": 124.99, "unit_cost": 54.00,
     "available_sizes": ["7","8","9","10","11","12"],
     "available_widths": ["D"], "total_stock": 144,
     "supplier_id": "SUP-SALOMON-01",
     "description": "Aggressive lug trail shoe for technical terrain. Black/orange."},
    {"sku": "SHOE-DRESS-BRN", "retailer_id": "RTL-FORMFIT", "name": "Oxford Executive Leather Dress Shoe",
     "category": "dress", "price": 189.99, "unit_cost": 88.00,
     "available_sizes": ["8","9","10","11","12"],
     "available_widths": ["D","EE"], "total_stock": 60,
     "supplier_id": "SUP-ALLEN-01",
     "description": "Premium leather oxford for business formal. Brown."},
    {"sku": "SHOE-XFIT-WHT", "retailer_id": "RTL-FORMFIT", "name": "CrossFit Trainer 5.0 Wide",
     "category": "training", "price": 109.99, "unit_cost": 48.00,
     "available_sizes": ["8","9","10","11","12","13"],
     "available_widths": ["D","2E","4E"], "total_stock": 204,
     "supplier_id": "SUP-REEBOK-01",
     "description": "Stable wide-fit cross-training shoe for gym and WODs."},
    {"sku": "SHOE-SLIP-BLK", "retailer_id": "RTL-STRIDE", "name": "ComfortWalk Slip-On Casual",
     "category": "casual", "price": 79.99, "unit_cost": 32.00,
     "available_sizes": ["7","8","9","10","11","12"],
     "available_widths": ["D","2E"], "total_stock": 360,
     "supplier_id": "SUP-SKECHERS-01",
     "description": "Lightweight memory foam slip-on for all-day wear."},
]

SUPPLIERS = [
    {"supplier_id": "SUP-NIKE-01", "name": "Nike Direct", "lead_time_days": 7, "moq": 24, "reliability_score": 0.97},
    {"supplier_id": "SUP-SALOMON-01", "name": "Salomon Wholesale", "lead_time_days": 14, "moq": 12, "reliability_score": 0.91},
    {"supplier_id": "SUP-ALLEN-01", "name": "Allen Edmonds B2B", "lead_time_days": 21, "moq": 6, "reliability_score": 0.88},
    {"supplier_id": "SUP-REEBOK-01", "name": "Reebok Distribution", "lead_time_days": 10, "moq": 18, "reliability_score": 0.94},
    {"supplier_id": "SUP-SKECHERS-01", "name": "Skechers Wholesale", "lead_time_days": 5, "moq": 24, "reliability_score": 0.99},
]

SOCIAL_POSTS = [
    # Viral ramp for PEG41 — 4 posts, drives surge signal
    {"platform": "tiktok", "post_text": "ok these grey cushioned runners are actually unreal 😭 everyone at the gym has them now #pegasus41", "sku": "SHOE-PEG41-GRY", "engagement_score": 9.2, "hours_ago": 6},
    {"platform": "reddit", "post_text": "Finally found a marathon shoe that doesn't destroy my knees — the grey pegasus max cushion ones from Nike. 10/10", "sku": "SHOE-PEG41-GRY", "engagement_score": 7.8, "hours_ago": 10},
    {"platform": "tiktok", "post_text": "POV you find out the Peg 41 grey is $139 and you buy 2 pairs 😂💸", "sku": "SHOE-PEG41-GRY", "engagement_score": 8.1, "hours_ago": 14},
    {"platform": "instagram", "post_text": "Marathon training in the Pegasus 41 greys — these are a game changer for long runs", "sku": "SHOE-PEG41-GRY", "engagement_score": 6.5, "hours_ago": 18},
    # Noise — should NOT fire a surge
    {"platform": "twitter", "post_text": "anyone know a good trail shoe?", "sku": None, "engagement_score": 0.5, "hours_ago": 2},
    {"platform": "reddit", "post_text": "Looking for wide fit options under $120", "sku": None, "engagement_score": 0.3, "hours_ago": 5},
]


def seed_retailers():
    print("Seeding retailers...")
    BQ.insert_rows_json(f"{DATASET}.retailers", RETAILERS)
    print(f"  {len(RETAILERS)} retailers")


def seed_warehouses():
    print("Seeding warehouses...")
    BQ.insert_rows_json(f"{DATASET}.warehouses", WAREHOUSES)
    print(f"  {len(WAREHOUSES)} warehouses")


def seed_stores():
    print("Seeding stores...")
    BQ.insert_rows_json(f"{DATASET}.stores", STORES)
    print(f"  {len(STORES)} stores across {len(RETAILERS)} retailers")


def seed_suppliers():
    print("Seeding suppliers...")
    BQ.insert_rows_json(f"{DATASET}.suppliers", SUPPLIERS)


def seed_products():
    print("Seeding products + embeddings...")
    rows = []
    for p in PRODUCTS:
        embedding = generate_embedding(p["description"])
        rows.append({**p, "embedding": embedding})
    BQ.insert_rows_json(f"{DATASET}.products", rows)
    print(f"  {len(rows)} products with embeddings")


def seed_sales():
    print("Seeding 18 months of sales history (12 stores)...")
    rows = []
    today = date.today()
    # Size curve: sizes 9-10 sell 3x faster
    size_multiplier = {"9": 1.5, "10": 1.5, "8": 0.8, "11": 0.8, "7": 0.4, "12": 0.5, "13": 0.3}
    for p in PRODUCTS:
        # Determine which stores carry this product (by retailer)
        product_stores = [s for s in STORES if s["retailer_id"] == p["retailer_id"]]
        for i in range(540):  # 18 months
            d = today - timedelta(days=i)
            base = random.randint(2, 8)
            # Weekend spike
            if d.weekday() in (5, 6):
                base = int(base * 1.6)
            # PEG41 viral ramp last 4 days
            if p["sku"] == "SHOE-PEG41-GRY" and i < 4:
                base = int(base * 4.5)
            # Dress shoes slow mover (planted)
            if p["sku"] == "SHOE-DRESS-BRN":
                base = max(1, base // 3)
            for store in product_stores:
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
    print(f"  {len(rows)} sales rows")


def seed_social_signals():
    print("Seeding social signals...")
    now = time.time()
    rows = [
        {
            "post_id": str(uuid.uuid4())[:8],
            "platform": post["platform"],
            "post_text": post["post_text"],
            "sku": post.get("sku"),
            "engagement_score": post["engagement_score"],
            "posted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - post["hours_ago"] * 3600)),
        }
        for post in SOCIAL_POSTS
    ]
    BQ.insert_rows_json(f"{DATASET}.social_signals", rows)
    print(f"  {len(rows)} posts")


def seed_arima_forecast():
    print("Seeding ARIMA baseline (31 units for PEG41)...")
    now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    BQ.insert_rows_json(f"{DATASET}.stockout_forecast", [{
        "sku": "SHOE-PEG41-GRY", "horizon_days": 7,
        "forecast_timestamp": now_str, "forecast_value": 31.0,
        "prediction_interval_lower_bound": 22.0,
        "prediction_interval_upper_bound": 40.0,
        "computed_at": now_str,
    }])


def seed_firestore_inventory():
    print("Seeding Firestore store inventory (12 stores)...")
    count = 0
    for p in PRODUCTS:
        product_stores = [s for s in STORES if s["retailer_id"] == p["retailer_id"]]
        per_store = max(2, p["total_stock"] // len(product_stores))
        for store in product_stores:
            doc_id = f"{p['sku']}_{store['store_id']}"
            # STR-04 gets critically low PEG41 stock for demo
            on_hand = 2 if (p["sku"] == "SHOE-PEG41-GRY" and store["store_id"] == "STR-04") else per_store
            FS.collection("store_inventory").document(doc_id).set({
                "sku": p["sku"], "store_id": store["store_id"],
                "retailer_id": p["retailer_id"],
                "on_hand": on_hand, "reserved": 0,
            })
            count += 1
    print(f"  {count} store inventory docs")

    print("Seeding Firestore warehouse inventory (4 warehouses)...")
    count = 0
    for p in PRODUCTS:
        product_warehouses = [
            w for w in WAREHOUSES
            if any(s["retailer_id"] == p["retailer_id"] and s["warehouse_id"] == w["warehouse_id"] for s in STORES)
        ]
        for wh in product_warehouses:
            doc_id = f"{p['sku']}_{wh['warehouse_id']}"
            FS.collection("warehouse_inventory").document(doc_id).set({
                "sku": p["sku"], "warehouse_id": wh["warehouse_id"],
                "retailer_id": p["retailer_id"],
                "on_hand": random.randint(50, 200),
                "reserved": 0,
                "safety_stock": 24,
            })
            count += 1
    print(f"  {count} warehouse inventory docs")

    # Also insert BQ warehouse_inventory snapshot
    now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    wh_rows = []
    for p in PRODUCTS:
        for wh in WAREHOUSES:
            if any(s["retailer_id"] == p["retailer_id"] and s["warehouse_id"] == wh["warehouse_id"] for s in STORES):
                wh_rows.append({
                    "warehouse_id": wh["warehouse_id"], "sku": p["sku"],
                    "on_hand": random.randint(50, 200), "reserved": 0,
                    "safety_stock": 24, "last_updated": now_str,
                })
    BQ.insert_rows_json(f"{DATASET}.warehouse_inventory", wh_rows)
    print(f"  {len(wh_rows)} warehouse_inventory rows in BigQuery")


if __name__ == "__main__":
    seed_retailers()
    seed_warehouses()
    seed_stores()
    seed_suppliers()
    seed_products()
    seed_sales()
    seed_social_signals()
    seed_arima_forecast()
    seed_firestore_inventory()
    print("\nSeed complete.")
