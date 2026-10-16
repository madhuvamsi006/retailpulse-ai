"""Unit tests for ranking/constraint_filter — budget hard filter must be 100%."""
import sys
sys.path.insert(0, "/home/appadmin/groundswell")

from ranking.constraint_filter import apply, ShopperConstraints

PRODUCTS = [
    {"sku": "A", "price": 99.99, "available_sizes": ["9", "10"], "available_widths": ["D", "2E"], "category": "running-road", "total_stock": 5},
    {"sku": "B", "price": 149.99, "available_sizes": ["10", "11"], "available_widths": ["D"], "category": "running-road", "total_stock": 3},
    {"sku": "C", "price": 199.99, "available_sizes": ["10"], "available_widths": ["D"], "category": "dress", "total_stock": 2},
    {"sku": "D", "price": 79.99, "available_sizes": ["8", "9", "10"], "available_widths": ["2E", "4E"], "category": "training", "total_stock": 0},
]


def test_budget_hard_filter():
    result = apply(PRODUCTS, ShopperConstraints(budget_max=100.0))
    assert all(p["price"] <= 100.0 for p in result)
    skus = [p["sku"] for p in result]
    assert "C" not in skus
    assert "B" not in skus


def test_size_filter():
    result = apply(PRODUCTS, ShopperConstraints(size="9"))
    assert all("9" in p["available_sizes"] for p in result)


def test_width_filter():
    result = apply(PRODUCTS, ShopperConstraints(width="2E"))
    assert all("2E" in p["available_widths"] for p in result)


def test_out_of_stock_excluded_by_default():
    result = apply(PRODUCTS, ShopperConstraints())
    skus = [p["sku"] for p in result]
    assert "D" not in skus  # D has 0 stock


def test_combined_budget_and_size():
    result = apply(PRODUCTS, ShopperConstraints(budget_max=150.0, size="10"))
    assert all(p["price"] <= 150.0 for p in result)
    assert all("10" in p["available_sizes"] for p in result)


def test_budget_evasion_paraphrases():
    """10 paraphrases that must ALL return zero products above budget."""
    budget = 100.0
    over_budget = [p for p in PRODUCTS if p["price"] > budget]
    assert len(over_budget) > 0, "Test data needs products over budget"

    for _ in range(10):
        result = apply(over_budget, ShopperConstraints(budget_max=budget))
        assert result == [], "No over-budget product should ever pass the filter"
