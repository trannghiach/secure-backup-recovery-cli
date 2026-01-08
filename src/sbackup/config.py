import os
from pathlib import Path

# --- BASE PATHS ---
BASE_DIR = Path(os.getcwd())
STORE_DIR = BASE_DIR / "store"

# --- CURRENT STORE PATH (Runtime config) ---
CURRENT_STORE_PATH = "store"

# --- POLICY ---
POLICY_FILE = BASE_DIR / "policy.yaml"

# --- AUDIT LOG ---
AUDIT_LOG_FILE = STORE_DIR / "audit.log"
# Env var để override audit log path (dùng cho testing)
AUDIT_LOG_ENV_VAR = "SBACKUP_AUDIT_LOG_PATH"

# --- WAL (Write-Ahead Logging) ---
WAL_JOURNAL_FILE = STORE_DIR / "journal.wal"
# Bật/tắt WAL (mặc định bật)
WAL_ENABLED = True

# --- CHUNKING ---
# Chunk size 1MB theo khuyến nghị
CHUNK_SIZE = 1024 * 1024

# --- HELPER FUNCTIONS ---
def get_audit_log_path() -> Path:
    """
    Lấy đường dẫn audit log:
    1. Ưu tiên env var SBACKUP_AUDIT_LOG_PATH (dùng cho testing)
    2. Mặc định: CWD/<CURRENT_STORE_PATH>/audit.log (lưu cùng store của user)
    """
    env_path = os.environ.get(AUDIT_LOG_ENV_VAR)
    if env_path:
        return Path(env_path)
    return Path.cwd() / CURRENT_STORE_PATH / "audit.log"

def set_store_path(store_path: str):
    """Cập nhật CURRENT_STORE_PATH (được gọi từ init_cmd)."""
    global CURRENT_STORE_PATH
    CURRENT_STORE_PATH = store_path
