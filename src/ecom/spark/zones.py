"""Storage-zone paths for the ingestion and Spark cleaning stages.

Every path comes from an environment variable with a local-filesystem
default, so the same code runs unchanged if the raw and processed zones
later move to MinIO.

``SOURCE_DATA_DIR`` was lost when the original ``data_ingestion/config.py``
and ``spark/config.py`` collided during a flattened upload. It is restored
here so both stages read their paths from one place.
"""

import os
from pathlib import Path

SOURCE_DATA_DIR = Path(os.environ.get("OLIST_SOURCE_DIR", "data"))
RAW_ZONE_DIR = Path(os.environ.get("OLIST_RAW_ZONE_DIR", "storage/raw/olist"))
PROCESSED_ZONE_DIR = Path(os.environ.get("OLIST_PROCESSED_ZONE_DIR", "storage/processed/olist"))
QUARANTINE_ZONE_DIR = Path(os.environ.get("OLIST_QUARANTINE_ZONE_DIR", "storage/quarantine/olist"))
REPORTS_DIR = Path(os.environ.get("OLIST_REPORTS_DIR", "storage/reports"))
