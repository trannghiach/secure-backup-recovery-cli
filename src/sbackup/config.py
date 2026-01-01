import os
from pathlib import Path

BASE_DIR = Path(os.getcwd())
STORE_DIR = BASE_DIR / "store"
# Chunk size 1MB theo khuyến nghị
CHUNK_SIZE = 1024 * 1024 
AUDIT_LOG_FILE = STORE_DIR / "audit.log"
POLICY_FILE = BASE_DIR / "policy.yaml"