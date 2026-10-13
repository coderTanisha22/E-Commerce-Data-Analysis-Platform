"""Configuration for the Spark cleaning stage.

Mirrors data_ingestion/config.py's pattern: every path comes from an
environment variable with a local-filesystem default, so the same code
runs unchanged if the raw/processed zones later move to MinIO.
"""

import os
from pathlib import Path

RAW_ZONE_DIR = Path(os.environ.get("OLIST_RAW_ZONE_DIR", "storage/raw/olist"))
PROCESSED_ZONE_DIR = Path(os.environ.get("OLIST_PROCESSED_ZONE_DIR", "storage/processed/olist"))
QUARANTINE_ZONE_DIR = Path(os.environ.get("OLIST_QUARANTINE_ZONE_DIR", "storage/quarantine/olist"))
REPORTS_DIR = Path(os.environ.get("OLIST_REPORTS_DIR", "storage/reports"))
