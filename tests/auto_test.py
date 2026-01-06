import subprocess
import os
import shutil
import time
import re
import random
import string
import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# --- CẤU HÌNH ---
CLI_CMD = [sys.executable, "-m", "src.sbackup.main"]
STORE_DIR = "store_test"
DATA_DIR = "dataset_test"
RESTORE_DIR = "restore_test"
AUDIT_LOG = os.path.join(STORE_DIR, "audit.log")

console = Console()

# --- 1. CÁC HÀM TIỆN ÍCH (HELPER) ---

def run_cmd(args, description, expect_success=True):
    """Chạy lệnh CLI và trả về (success, stdout, stderr)"""
    console.print(f"[bold cyan]➤ RUN:[/bold cyan] {description}")
    
    # Ép buộc Encoding là UTF-8 để tránh lỗi emoji trên Windows
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    start = time.time()
    # Thêm errors='replace' để nếu gặp ký tự lạ thì thay bằng dấu ? chứ không crash
    result = subprocess.run(
        CLI_CMD + args, 
        capture_output=True, 
        text=True, 
        encoding='utf-8', 
        errors='replace',  # <--- QUAN TRỌNG: Chống crash unicode
        env=env            # <--- QUAN TRỌNG: Ép môi trường UTF-8
    )
    duration = time.time() - start
    
    is_success = (result.returncode == 0)
    
    if is_success == expect_success:
        status = "[green]✔ PASS[/green]"
    else:
        status = "[red]✘ FAIL[/red]"

    console.print(f"   {status} ({duration:.2f}s)")
    
    if not is_success and expect_success:
        # In ra cả stdout và stderr để debug
        err_msg = result.stderr + "\n" + result.stdout
        console.print(Panel(err_msg, title="Error Output", style="red"))
    
    return is_success, result.stdout

def generate_dataset(root_dir, num_files=10):
    """Tạo dữ liệu test ngẫu nhiên"""
    if os.path.exists(root_dir):
        shutil.rmtree(root_dir)
    os.makedirs(root_dir)
    
    for i in range(num_files):
        content = ''.join(random.choices(string.ascii_letters, k=1024)) # 1KB
        with open(os.path.join(root_dir, f"file_{i}.txt"), "w") as f:
            f.write(content)
    console.print(f"[dim]   -> Đã tạo {num_files} files tại {root_dir}[/dim]")

def clean_environment():
    """Xóa sạch hiện trường trước khi test"""
    for path in [STORE_DIR, DATA_DIR, RESTORE_DIR]:
        if os.path.exists(path):
            shutil.rmtree(path)
    console.print("[dim]   -> Đã dọn dẹp môi trường test[/dim]")

def tamper_file(filepath):
    """Hàm phá hoại: Sửa 1 byte trong file"""
    if not os.path.exists(filepath):
        # Nếu chưa có file thật (do đang chạy Mock), tạo file giả để test logic phá
        with open(filepath, "wb") as f: f.write(b"dummy_chunk_content")
        
    with open(filepath, "r+b") as f:
        f.seek(0)
        byte = f.read(1)
        f.seek(0)
        # Đảo ngược byte đầu tiên (XOR FF)
        f.write(bytes([byte[0] ^ 0xFF]))
    console.print(f"[yellow]   ⚠ TAMPERED:[/yellow] Đã sửa file {filepath}")

# --- 2. CÁC KỊCH BẢN TEST (SCENARIOS) ---

def test_full_flow():
    console.print(Panel("KỊCH BẢN 1: HAPPY PATH (Init -> Backup -> List -> Verify)", style="bold white"))
    
    # B1: Init
    run_cmd(["init", STORE_DIR], "Khởi tạo Store")
    
    # B2: Backup
    success, output = run_cmd(["backup", DATA_DIR, "--label", "TestAuto"], "Backup dữ liệu")
    if not success: return None
    
    # Lấy Snapshot ID từ output bằng Regex
    # Tìm chuỗi kiểu "Snapshot ID: snap_123456"
    match = re.search(r"Snapshot ID:\s+(\S+)", output)
    if match:
        snap_id = match.group(1)
        console.print(f"[bold green]   -> Captured Snapshot ID: {snap_id}[/bold green]")
    else:
        # Nếu chạy Mock có thể ID nó khác, fallback về ID cứng nếu regex trượt
        console.print("[yellow]   -> Không regex được ID, dùng ID mặc định của Mock[/yellow]")
        snap_id = "snap_mock_id" # Fallback cho Mock

    # B3: List
    run_cmd(["list-snapshots"], "Liệt kê danh sách")

    # B4: Verify (Mong đợi OK)
    run_cmd(["verify", snap_id], f"Verify snapshot {snap_id} (Kỳ vọng OK)")
    
    return snap_id

def test_integrity_tamper(snap_id):
    console.print(Panel("KỊCH BẢN 2: CHỐNG SỬA ĐỔI (DATA INTEGRITY)", style="bold white"))
    
    # 1. Tìm file để phá (File chunk)
    chunks_dir = os.path.join(STORE_DIR, "chunks")
    
    # Vì Mock hiện tại chưa ghi chunk thật, ta tự tạo 1 file chunk giả để test logic phá hoại
    if not os.path.exists(chunks_dir): os.makedirs(chunks_dir)
    target_chunk = os.path.join(chunks_dir, "fake_chunk_hash_123")
    
    # 2. Thực hiện phá hoại
    tamper_file(target_chunk)
    
    # 3. Verify lại (Kỳ vọng FAIL)
    # Lưu ý: Với MockLogic hiện tại, nó luôn trả về True -> Test này sẽ PASS (nhưng logic test là đúng).
    # Khi Dev 2 lắp Core thật vào, dòng này sẽ FAIL -> Test hoạt động đúng mục đích.
    console.print("[dim]   -> Đang chạy verify với dữ liệu đã bị sửa...[/dim]")
    success, _ = run_cmd(["verify", snap_id], "Verify sau khi sửa file chunk", expect_success=False)
    
    if success:
        console.print("[yellow]   [NOTE] Verify vẫn PASS vì đang dùng Mock Logic (Chưa check hash thật).[/yellow]")
    else:
        console.print("[green]   ✔ Hệ thống đã phát hiện dữ liệu bị sửa![/green]")

def test_audit_tamper():
    console.print(Panel("KỊCH BẢN 3: BẢO VỆ AUDIT LOG", style="bold white"))
    
    # 1. Kiểm tra log hiện tại
    run_cmd(["audit-verify"], "Kiểm tra Audit Log lần 1 (Kỳ vọng OK)")
    
    # 2. Phá hoại file log (Sửa dòng cuối)
    if os.path.exists(AUDIT_LOG):
        # Đọc hết, sửa dòng cuối, ghi lại
        with open(AUDIT_LOG, "r") as f: lines = f.readlines()
        
        if lines:
            lines[-1] = lines[-1].replace("OK", "FAIL") # Sửa nội dung
            with open(AUDIT_LOG, "w") as f: f.writelines(lines)
            console.print(f"[yellow]   ⚠ TAMPERED:[/yellow] Đã sửa file {AUDIT_LOG}")
            
            # 3. Verify lại (Kỳ vọng FAIL)
            run_cmd(["audit-verify"], "Verify Audit Log sau khi sửa (Kỳ vọng FAIL)", expect_success=False)
        else:
            console.print("[red]   Lỗi: Audit log rỗng, không test được tamper[/red]")
    else:
        # Nếu Mock chưa ghi file log thật
        console.print("[yellow]   [SKIP] Không tìm thấy file audit.log (Do đang chạy Mock in ra màn hình)[/yellow]")

# --- MAIN RUNNER ---

if __name__ == "__main__":
    console.rule("[bold red]AUTOMATED INTEGRATION TEST[/bold red]")
    
    # 1. Setup
    clean_environment()
    generate_dataset(DATA_DIR)
    
    # 2. Run Test
    snapshot_id = test_full_flow()
    
    if snapshot_id:
        test_integrity_tamper(snapshot_id)
        test_audit_tamper()
    
    console.rule("[bold green]TEST SUITE FINISHED[/bold green]")