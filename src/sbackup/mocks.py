# src/sbackup/mocks.py
import time
from typing import List
from .contracts import SnapshotManifest, OpResult
# Import đúng giao diện bạn đã push
from .interfaces import IStorage, ILogic, ISecurity

class MockStorage:
    # Interface của bạn không có init_store, nên ta không implement ở đây
    # Logic init sẽ xử lý tạm bên main hoặc constructor
    
    def save_chunk(self, chunk_hash: str, data: bytes) -> bool:
        # Khớp interface: trả về bool
        return True 

    def get_chunk(self, chunk_hash: str) -> bytes:
        return b"mock_data_content"

    def save_manifest(self, manifest: SnapshotManifest) -> bool:
        # Khớp interface: trả về bool
        return True

    def load_manifest(self, snapshot_id: str) -> SnapshotManifest:
        return SnapshotManifest(
            snapshot_id=snapshot_id,
            label="Mock Snapshot",
            merkle_root="mock_root_123"
        )

    def list_snapshots(self) -> List[str]:
        return ["snap_1704153600", "snap_1704153601"]

class MockLogic:
    def chunk_data(self, file_path: str) -> List[str]:
        # Khớp interface: Trả về List[str] (chỉ là hash string, không phải object ChunkEntry)
        return ["hash_abc_123", "hash_def_456"]

    def create_manifest(self, label: str, root_path: str) -> SnapshotManifest:
        return SnapshotManifest(
            snapshot_id=f"snap_{int(time.time())}",
            label=label,
            merkle_root="mock_merkle_root_hash"
        )

    def verify_merkle(self, manifest: SnapshotManifest) -> bool:
        return True

class MockSecurity:
    def get_current_user(self) -> str:
        return "admin_test"

    def check_permission(self, user: str, command: str) -> bool:
        return True

    def log_audit(self, user: str, command: str, args: str, status: str):
        # In tạm ra console để debug vì interface này không return gì
        print(f"   [MOCK AUDIT] {user} | {command} | {status}")
        
    def verify_audit_log(self) -> bool:
        print("   [MOCK] Verifying audit log signature...")
        return True