"""
Constraint filter — deterministic hard filter, zero LLM calls.
Enforces budget, size, width, stock, and category constraints.
"""
from dataclasses import dataclass
from typing import Any


@dataclass
class ShopperConstraints:
    budget_max: float | None = None
    size: str | None = None
    width: str | None = None
    categories: list[str] | None = None
    in_stock_only: bool = True
    store_id: str | None = None


def apply(products: list[dict[str, Any]], constraints: ShopperConstraints) -> list[dict[str, Any]]:
    """
    Hard-filter products against shopper constraints.
    A product over budget_max is NEVER returned, regardless of any LLM output.
    """
    result = []
    for p in products:
        if constraints.budget_max is not None and p.get("price", 0) > constraints.budget_max:
            continue

        if constraints.size is not None:
            available_sizes = [str(s) for s in p.get("available_sizes", [])]
            if str(constraints.size) not in available_sizes:
                continue

        if constraints.width is not None:
            available_widths = [w.upper() for w in p.get("available_widths", [])]
            if constraints.width.upper() not in available_widths:
                continue

        if constraints.categories:
            p_category = p.get("category", "").lower()
            if not any(c.lower() in p_category for c in constraints.categories):
                continue

        if constraints.in_stock_only:
            stock_key = f"stock_{constraints.store_id}" if constraints.store_id else "total_stock"
            if p.get(stock_key, p.get("total_stock", 0)) <= 0:
                continue

        result.append(p)

    return result
