"""Deterministic synthetic product name generator for display and visualization.

Generates realistic, plausible e-commerce product titles anchored to the
Olist category and product ID hash. Keeps upstream warehouse data pure while
providing human-readable titles in the API, graph visualizer, and dashboard.
"""

from __future__ import annotations

_ADJECTIVES: tuple[str, ...] = (
    "Premium",
    "Classic",
    "Modern",
    "Compact",
    "Ergonomic",
    "Deluxe",
    "Essential",
    "Professional",
    "Signature",
    "Urban",
    "Artisan",
    "Eco",
)

_STYLES: tuple[str, ...] = (
    "Edition",
    "Series",
    "Collection",
    "Pack",
    "Set",
    "Bundle",
    "Kit",
    "Model",
)


def synthesize_product_name(product_id: str, category: str | None = None) -> str:
    """Deterministically synthesize a realistic product title.

    Uses the product_id hex hash as a seed so that the same product ID always
    produces the exact same title across runs, APIs, and dashboard refreshes.

    Args:
        product_id: 32-character hexadecimal product identifier.
        category: English category name if available.

    Returns:
        Plausible product display title (e.g. 'Deluxe Watches Gifts Series · #4244').
    """
    clean_id = str(product_id).strip()
    short_hash = clean_id[:4].upper() if len(clean_id) >= 4 else clean_id.upper()

    try:
        seed = int(clean_id[:8], 16)
    except ValueError:
        seed = abs(hash(clean_id))

    adj = _ADJECTIVES[seed % len(_ADJECTIVES)]
    style = _STYLES[(seed >> 4) % len(_STYLES)]

    if not category or category == "unknown":
        return f"{adj} Marketplace Item {style} · #{short_hash}"

    clean_category = category.replace("_", " ").title()
    return f"{adj} {clean_category} {style} · #{short_hash}"
