import os
import shutil
import json
import sys
import hashlib
from pathlib import Path

# Thêm đường dẫn để import được các module cha (sbackup package)
sys.path.insert(0, str(Path(__file__).parent.parent))

from sbackup.core.logic import BasicLogic
from restore import Repository
from sbackup.contracts import OpResult, SnapshotManifest
from sbackup.core.utils import create_canonical_manifest

# --- CẤU HÌNH MẶC ĐỊNH ---
TEST_ENV_DIR = Path("test_env")
DEFAULT_SOURCE_DIR = TEST_ENV_DIR / "dataset"
STORE_DIR = Path(__file__).parent.parent / "store"
RESTORE_DIR = Path(__file__).parent / "restored"

# Biến toàn cục lưu trạng thái phiên làm việc
session_context = {
    "source_dir": None,       # Thư mục gốc cần backup
    "snapshot_id": None,      # ID của snapshot vừa tạo hoặc được chọn
    "restore_dir": RESTORE_DIR # Thư mục sẽ restore ra
}

class TestStorage(Repository):
    """
    Class mở rộng Repository để hỗ trợ việc GHI dữ liệu (Backup).
    """
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

# --- CÁC HÀM HỖ TRỢ ---
def create_dummy_data():
    """Tạo dữ liệu giả lập nếu user chọn"""
    print(f"Creating dummy dataset at {DEFAULT_SOURCE_DIR}...")
    if TEST_ENV_DIR.exists():
        shutil.rmtree(TEST_ENV_DIR)
    
    os.makedirs(DEFAULT_SOURCE_DIR)
    os.makedirs(RESTORE_DIR)

    # Helper tạo file
    def _create_file(rel_path, content):
        p = DEFAULT_SOURCE_DIR / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = 'w' if isinstance(content, str) else 'wb'
        with open(p, mode) as f:
            f.write(content)

    _create_file("file1.txt", "Hello World " * 100)
    _create_file("image.bin", os.urandom(1024 * 1024 * 2)) # 2MB
    _create_file("subfolder/deep.txt", "Deep file content")
    
    print("Dummy data created.")
    return DEFAULT_SOURCE_DIR

def get_file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def verify_content(src, dst):
    """So sánh nội dung 2 thư mục"""
    print(f"Comparing source: {src}")
    print(f"       and dest:   {dst}")
    diffs = []
    src = Path(src)
    dst = Path(dst)
    
    for root, dirs, files in os.walk(src):
        rel_root = Path(root).relative_to(src)
        dst_root = dst / rel_root
        
        for f in files:
            src_file = Path(root) / f
            dst_file = dst_root / f
            
            if not dst_file.exists():
                diffs.append(f"Missing file: {rel_root}/{f}")
                continue
                
            if get_file_hash(src_file) != get_file_hash(dst_file):
                diffs.append(f"Content mismatch: {rel_root}/{f}")
    return diffs

# --- CÁC MENU FUNCTION ---

def step_setup():
    """1: Chọn thư mục nguồn"""
    print("\n--- STEP 1: SETUP SOURCE ---")
    print("1. Use Auto-generated Dummy Data (test_env/dataset)")
    print("2. Choose an existing folder on your computer")
    
    choice = input("Select option (1/2): ").strip()
    
    if choice == '2':
        path_str = input("Enter full path to folder to backup: ").strip()
        path = Path(__file__).parent.parent / "restore" / path_str
        if not path.exists() or not path.is_dir():
            print("Error: Invalid path or not a directory.")
            return
        session_context["source_dir"] = path
    else:
        # Default is dummy data
        path = create_dummy_data()
        session_context["source_dir"] = path

    print(f">> Source directory set to: {session_context['source_dir']}")

def step_backup():
    """2: Thực hiện Backup"""
    print("\n--- STEP 2: BACKUP ---")
    source = session_context["source_dir"]
    if not source:
        print("Error: Please run Step 1 (Setup) first to select a source folder.")
        return

    label = input(f"Enter label for backup (default: 'manual-backup'): ").strip() or "manual-backup"
    
    # Init Storage
    storage = TestStorage(str(STORE_DIR))
    storage.init()
    logic = BasicLogic(storage)

    print(f"Processing backup for: {source}...")
    try:
        manifest = logic.create_manifest(label, str(source))
        storage.save_manifest(manifest)
        
        session_context["snapshot_id"] = manifest.snapshot_id
        print(f">> Backup SUCCESS.")
        print(f">> Snapshot ID (Merkle Root): {manifest.snapshot_id}")
    except Exception as e:
        print(f"Backup FAILED: {e}")

def step_restore():
    """3: Thực hiện Restore"""
    print("\n--- STEP 3: RESTORE ---")
    
    # Init Repo (Read-only)
    repo = Repository(str(STORE_DIR))
    snapshots = repo.list_snapshots()
    
    if not snapshots:
        print("No snapshots found in store.")
        return

    print("Available Snapshots:")
    for idx, snap in enumerate(snapshots):
        print(f"{idx + 1}. {snap}")

    # Logic chọn Snapshot
    selected_snap = session_context.get("snapshot_id")
    if selected_snap and selected_snap in snapshots:
        print(f"Current selected snapshot from previous step: {selected_snap}")
        choice = input("Press ENTER to use current, or type number to change: ").strip()
        if choice:
            try:
                selected_snap = snapshots[int(choice) - 1]
            except (ValueError, IndexError):
                print("Invalid selection.")
                return
    else:
        choice = input("Select snapshot number: ").strip()
        try:
            selected_snap = snapshots[int(choice) - 1]
        except (ValueError, IndexError):
            print("Invalid selection.")
            return
            
    # Logic chọn thư mục đích
    dest = input(f"Enter restore path (default: {RESTORE_DIR}): ").strip()
    if not dest:
        dest_path = RESTORE_DIR
    else:
        dest_path = Path(__file__).parent / dest

    # Thực hiện Restore
    result = repo.restore(selected_snap, str(dest_path))
    
    if result.success:
        print(f">> Restore SUCCESS: {result.message}")
        session_context["restore_dir"] = dest_path
        session_context["snapshot_id"] = selected_snap # Update context
    else:
        print(f">> Restore FAILED: {result.message}")

def step_verify():
    """4: So sánh dữ liệu"""
    print("\n--- STEP 4: VERIFY DATA ---")
    src = session_context["source_dir"]
    dst = session_context["restore_dir"]
    
    if not src or not dst:
        print("Error: Missing source or restore directory in context.")
        print("Please Run Step 1 (Source) and Step 3 (Restore) first.")
        # Cho phép nhập tay nếu mất context
        choice = input("Do you want to manually enter paths? (y/n): ").lower()
        if choice == 'y':
            src = input("Source path: ")
            dst = input("Restored path: ")
        else:
            return

    diffs = verify_content(src, dst)
    if not diffs:
        print(">> INTEGRITY CHECK PASSED: Data matches perfectly.")
    else:
        print(">> INTEGRITY CHECK FAILED:")
        for d in diffs: print(f" - {d}")

def step_tamper():
    """Bước 5: Test tấn công"""
    print("\n--- STEP 5: TAMPER TEST ---")
    snap_id = session_context["snapshot_id"]
    if not snap_id:
        print("Error: No snapshot selected. Run Backup or Restore first.")
        return

    manifest_path = STORE_DIR / "snapshots" / f"{snap_id}.json"
    if not manifest_path.exists():
        print("Snapshot file not found.")
        return

    print(f"Targeting snapshot: {snap_id}")
    print("Simulating attack: Modifying Merkle Root in manifest...")
    
    # Backup file gốc trước khi sửa
    backup_manifest = manifest_path.with_suffix(".json.bak")
    shutil.copy(manifest_path, backup_manifest)
    
    try:
        with open(manifest_path, 'r') as f:
            data = json.load(f)
        
        data['merkle_root'] = "deadbeef" * 8
        
        with open(manifest_path, 'w') as f:
            json.dump(data, f)
            
        print("Tampering applied.")
        print("Attempting to restore tampered snapshot...")
        
        repo = Repository(str(STORE_DIR))
        tamper_dst = TEST_ENV_DIR / "tampered_restore"
        result = repo.restore(snap_id, str(tamper_dst))
        
        if not result.success:
            print(f">> SECURITY TEST PASSED: System rejected the snapshot.")
            print(f"   Message: {result.message}")
        else:
            print(f">> SECURITY TEST FAILED: System restored corrupted data!")
            
    finally:
        # Khôi phục file gốc
        print("Restoring original manifest file...")
        shutil.move(backup_manifest, manifest_path)

def main_menu():
    while True:
        print("\n==========================================")
        print(f"BACKUP/RESTORE TEST TOOL")
        print(f"Current Source: {session_context['source_dir']}")
        print(f"Current Snapshot: {session_context['snapshot_id']}")
        print("==========================================")
        print("1. Setup / Select Source Folder")
        print("2. Perform Backup")
        print("3. Perform Restore")
        print("4. Verify Integrity (Source vs Restored)")
        print("5. Run Tamper Test (Security)")
        print("0. Exit")
        
        choice = input("Enter choice: ").strip()
        
        if choice == '1': step_setup()
        elif choice == '2': step_backup()
        elif choice == '3': step_restore()
        elif choice == '4': step_verify()
        elif choice == '5': step_tamper()
        elif choice == '0': sys.exit(0)
        else: print("Invalid choice.")

if __name__ == "__main__":
    # Tạo sẵn thư mục store nếu chưa có
    if not STORE_DIR.exists():
        os.makedirs(STORE_DIR)
    main_menu()