"""Synthetic inventory generation.

Olist records real sales but no stock levels, so the operational fields the
restock rule needs are generated here. Everything this package produces is
labelled synthetic and is never presented as real business data.
"""

from ecom.synthetic.inventory import (
    GeneratorParams,
    build_sales_base,
    classify_status,
    filter_funnel,
    generate_synthetic_inventory,
)

__all__ = [
    "GeneratorParams",
    "build_sales_base",
    "classify_status",
    "filter_funnel",
    "generate_synthetic_inventory",
]
