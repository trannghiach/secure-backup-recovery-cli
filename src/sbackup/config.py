import os
from pathlib import Path

# --- BASE PATHS ---
BASE_DIR = Path(os.getcwd())
STORE_DIR = BASE_DIR / "store"

# --- POLICY ---
POLICY_FILE = BASE_DIR / "policy.yaml"

# --- AUDIT LOG ---
AUDIT_LOG_FILE = STORE_DIR / "audit.log"
# Env var để override audit log path (dùng cho testing)
AUDIT_LOG_ENV_VAR = "SBACKUP_AUDIT_LOG_PATH"

# --- CHUNKING ---
# Chunk size 1MB theo khuyến nghị
CHUNK_SIZE = 1024 * 1024

# --- HELPER FUNCTIONS ---
def get_audit_log_path() -> Path:
    """
    Lấy đường dẫn audit log:
    1. Ưu tiên env var SBACKUP_AUDIT_LOG_PATH (dùng cho testing)
    2. Mặc định: CWD/store/audit.log (lưu cùng store của user)
    """
    env_path = os.environ.get(AUDIT_LOG_ENV_VAR)
    if env_path:
        return Path(env_path)
    return Path.cwd() / "store" / "audit.log"
