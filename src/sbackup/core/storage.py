import os
import json
import time
import hashlib
from pathlib import Path
from typing import List, Dict, Any
from ..contracts import OpResult, SnapshotManifest
from ..core.utils import compute_merkle_root, create_canonical_manifest

class StorageManager:
    def __init__(self, store_path: str = "store"):
        self.base_path = (Path(__file__).parent.parent / store_path).resolve()
        self.chunks_dir = self.base_path / 'chunks'
        self.snapshots_dir = self.base_path / "snapshots"
        self.audit_file = self.base_path / "audit.log"

    def init(self):
        os.makedirs(self.chunks_dir, exist_ok=True)
        os.makedirs(self.snapshots_dir, exist_ok=True)
        if not self.audit_file.exists():
            with open(self.audit_file, 'a'):
                pass
        print(f"Initialized repository at {self.base_path}")
        
    def save_chunk(self, chunk_hash: str, data: bytes) -> bool:
        chunk_path = self.chunks_dir / chunk_hash
        if chunk_path.exists():
            return False
        with open(chunk_path, 'wb') as f:
            f.write(data)
        return True

    def save_manifest(self, manifest: SnapshotManifest) -> bool:
        json_str = create_canonical_manifest(manifest)
        filename = f"{manifest.snapshot_id}.json"
        file_path = self.snapshots_dir / filename
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(json_str)
        return True

    def get_chunk(self, chunk_hash: str) -> bytes:
        chunk_path = self.chunks_dir / chunk_hash
        if not chunk_path.exists():
            raise FileNotFoundError(f"Chunk not found: {chunk_hash}")
        with open(chunk_path, 'rb') as f:
            return f.read()

    def load_manifest(self, snapshot_id: str) -> Dict[str, Any]:
        filename = snapshot_id if snapshot_id.endswith(".json") else f"{snapshot_id}.json"
        manifest_path = self.snapshots_dir / filename
        
        if not manifest_path.exists():
            raise FileNotFoundError(f"Snapshot {snapshot_id} not found")

        with open(manifest_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _verify_snapshot_integrity(self, manifest_data: Dict[str, Any]) -> bool:
        """
        Kiểm tra tính toàn vẹn của Manifest trước khi Restore.
        Phải tính lại Merkle Root và so sánh với root ghi trong manifest.
        Logic phải khớp với hàm create_manifest trong logic.py
        """
        try:
            stored_merkle_root = manifest_data.get('merkle_root', '')
            files = manifest_data.get('files', [])

            # Sắp xếp file theo path
            sorted_files = sorted(files, key=lambda x: x.get('path', ''))

            # Tính lại Hash của từng file
            per_file_hashes = []
            for f in sorted_files:
                path = f.get('path', '')
                chunks = f.get('chunks', [])
                
                s = path + ":" + ",".join(chunks)
                
                # Tính SHA-256
                file_hash = hashlib.sha256(s.encode("utf-8")).hexdigest()
                per_file_hashes.append(file_hash)

            # Tính lại Merkle Root từ danh sách hash
            computed_root = compute_merkle_root(per_file_hashes)

            # So sánh
            if computed_root != stored_merkle_root:
                print(f"[VERIFY FAIL] Merkle Mismatch!")
                print(f"Expected: {stored_merkle_root}")
                print(f"Computed: {computed_root}")
                return False
            
            return True

        except Exception as e:
            print(f"[VERIFY ERROR] {e}")
            return False

    def list_snapshots(self) -> List[str]:
        if not self.snapshots_dir.exists(): return []
        return [f.stem for f in self.snapshots_dir.glob("*.json")]

    def restore(self, snapshot_id: str, restore_path: str) -> OpResult:
        """
        Restore với quy trình an toàn:
        1. Load Manifest
        2. Verify Merkle Root (Chống giả mạo manifest)
        3. Restore Files
        """
        print(f"\n--- Starting restore for snapshot: {snapshot_id} ---")
        
        # B1: LOAD
        try:
            manifest_data = self.load_manifest(snapshot_id)
        except FileNotFoundError:
            return OpResult(success=False, message=f"Snapshot {snapshot_id} does not exist.")
        except json.JSONDecodeError:
            return OpResult(success=False, message=f"Snapshot {snapshot_id} corrupted (JSON error).")

        # B2: Verify trước khi restore
        print("Verifying snapshot integrity...")
        if not self._verify_snapshot_integrity(manifest_data):
            return OpResult(success=False, message="Integrity Check Failed: Merkle root mismatch. Snapshot may be tampered.")
        print("Snapshot integrity verified. Proceeding to restore files...")

        # B3: Restore files
        abs_restore_path = Path(restore_path).resolve()
        files_list = manifest_data.get('files', [])
        
        if not files_list:
            return OpResult(success=True, message="Snapshot is empty.")

        restored_count = 0
        for file_data in files_list:
            rel_path = file_data.get('path')
            chunks_hashes = file_data.get('chunks', [])
            mtime = file_data.get('mtime')

            if not rel_path: continue

            # Path Traversal Check
            dest_path = abs_restore_path / rel_path
            try:
                dest_path.resolve().relative_to(abs_restore_path)
            except ValueError:
                print(f"SECURITY ALERT: Skipping unsafe path {rel_path}")
                continue

            dest_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                with open(dest_path, 'wb') as f_out:
                    for chunk_hash in chunks_hashes:
                        try:
                            chunk_data = self.get_chunk(chunk_hash)
                            f_out.write(chunk_data)
                        except FileNotFoundError:
                            # Cleanup và Fail
                            f_out.close()
                            if dest_path.exists(): os.remove(dest_path)
                            return OpResult(success=False, message=f"Missing chunk {chunk_hash} for {rel_path}")

                if mtime is not None:
                    os.utime(dest_path, (time.time(), mtime))
                
                restored_count += 1
                
            except OSError as e:
                return OpResult(success=False, message=f"I/O Error: {str(e)}")

        success_msg = f"Successfully restored {restored_count} files from snapshot {snapshot_id}."
        print(success_msg)
        return OpResult(success=True, message=success_msg)