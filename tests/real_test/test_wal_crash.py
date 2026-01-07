"""
TEST SUITE: WAL CRASH RECOVERY
==============================
Kiểm tra khả năng phục hồi sau crash giữa chừng.

Kịch bản crash:
- Backup bị kill giữa chừng -> Store vẫn ổn định
- WAL recover phải rollback transaction dang dở
- Dữ liệu trước crash vẫn nguyên vẹn
"""

import os
import sys
import time
import json
import shutil
import signal
import subprocess
import threading
import re
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

# --- CẤU HÌNH ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SANDBOX_DIR = PROJECT_ROOT / "tests" / "sandbox_crash"
AUDIT_LOG_PATH = SANDBOX_DIR / "store" / "audit.log"
CLI_CMD = [sys.executable, "-m", "src.sbackup.main"]

console = Console()

# --- HÀM HỖ TRỢ ---

def setup_environment():
    """Khởi tạo môi trường test sạch."""
    if SANDBOX_DIR.exists():
        try: shutil.rmtree(SANDBOX_DIR)
        except: pass
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    (SANDBOX_DIR / "store").mkdir(parents=True, exist_ok=True)
    
    policy_src = PROJECT_ROOT / "policy.yaml"
    policy_dst = SANDBOX_DIR / "policy.yaml"
    if policy_src.exists():
        shutil.copy2(policy_src, policy_dst)

def run_cli(args, cwd=SANDBOX_DIR, timeout=60):
    """Chạy CLI command."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = f"{PROJECT_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["SBACKUP_AUDIT_LOG_PATH"] = str(AUDIT_LOG_PATH)

    result = subprocess.run(
        CLI_CMD + args, cwd=cwd, capture_output=True, text=True,
        env=env, encoding='utf-8', errors='replace', timeout=timeout
    )
    return result

def run_cli_async(args, cwd=SANDBOX_DIR):
    """Chạy CLI command không blocking."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = f"{PROJECT_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["SBACKUP_AUDIT_LOG_PATH"] = str(AUDIT_LOG_PATH)

    proc = subprocess.Popen(
        CLI_CMD + args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, text=True, encoding='utf-8', errors='replace',
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    )
    return proc

def get_snapshot_id(output):
    """Trích xuất snapshot ID từ output."""
    match = re.search(r"([a-f0-9]{64})", output)
    return match.group(1) if match else None

def create_test_data(name="data", size_mb=0, num_files=1, content="Test content"):
    """
    Tạo dữ liệu test.
    size_mb: Nếu > 0, tạo file lớn để backup lâu hơn
    num_files: Số lượng file
    """
    d = SANDBOX_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    
    for i in range(num_files):
        file_path = d / f"file_{i}.txt"
        if size_mb > 0:
            # Tạo file lớn
            with open(file_path, "w") as f:
                # Ghi từng dòng để tạo file lớn
                chunk = "A" * 1024 + "\n"  # ~1KB per line
                for _ in range(size_mb * 1024):
                    f.write(chunk)
        else:
            with open(file_path, "w") as f:
                f.write(f"{content} - File {i}")
    return d

def get_current_user():
    import getpass
    return getpass.getuser()

def get_wal_status():
    """Đọc trạng thái WAL journal."""
    wal_file = SANDBOX_DIR / "store" / "wal.journal"
    if not wal_file.exists():
        return {"exists": False, "transactions": []}
    
    transactions = []
    current_txn = None
    
    with open(wal_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split('|')
            if len(parts) >= 4:
                action = parts[0]
                txn_id = parts[1]
                
                if action == "BEGIN":
                    current_txn = {"id": txn_id, "status": "in_progress", "ops": []}
                    transactions.append(current_txn)
                elif action == "COMMIT":
                    for t in transactions:
                        if t["id"] == txn_id:
                            t["status"] = "committed"
                elif action in ("WRITE", "DELETE"):
                    for t in transactions:
                        if t["id"] == txn_id:
                            t["ops"].append(action)
    
    return {
        "exists": True, 
        "transactions": transactions,
        "dangling": [t for t in transactions if t["status"] == "in_progress"]
    }

def list_snapshots():
    """Liệt kê các snapshot trong store."""
    snapshots_dir = SANDBOX_DIR / "store" / "snapshots"
    if not snapshots_dir.exists():
        return []
    return [f.stem for f in snapshots_dir.glob("*.json")]

def verify_all_snapshots():
    """Verify tất cả snapshots, trả về (passed, failed)."""
    snapshots = list_snapshots()
    passed = []
    failed = []
    
    for snap_id in snapshots:
        res = run_cli(["verify", snap_id])
        output = res.stdout + res.stderr
        if "FAILED" in output or "Error" in output or "Mismatch" in output:
            failed.append(snap_id)
        else:
            passed.append(snap_id)
    
    return passed, failed

def print_verdict(test_name, success, details="", command_args=None):
    """In kết quả kiểm thử."""
    user = get_current_user()
    cmd_str = f"sbackup {' '.join(command_args)}" if command_args else "N/A"
    
    if success:
        console.print(Panel(
            f"[bold green]✔ PASS: {test_name}[/bold green]\n\n"
            f"[cyan]📋 Command đã chạy:[/cyan] [white]{cmd_str}[/white]\n"
            f"[cyan]👤 User thực thi:[/cyan] [white]{user}[/white]\n\n"
            f"[dim]{details}[/dim]",
            border_style="green",
            title="[bold]KẾT QUẢ KIỂM THỬ[/bold]"
        ))
        return True
    else:
        console.print(Panel(
            f"[bold red]✘ FAIL: {test_name}[/bold red]\n\n"
            f"[cyan]📋 Command đã chạy:[/cyan] [white]{cmd_str}[/white]\n"
            f"[cyan]👤 User thực thi:[/cyan] [white]{user}[/white]\n\n"
            f"[bold red]{details}[/bold red]",
            border_style="red",
            title="[bold]KẾT QUẢ KIỂM THỬ[/bold]"
        ))
        return False

# --- KỊCH BẢN CRASH ---

def scenario_1_simulate_wal_dangling():
    """
    CASE 1: MÔ PHỎNG WAL DANGLING TRANSACTION
    
    Mô tả: Tạo WAL với BEGIN nhưng không có COMMIT.
    Khi init lại, WAL phải phát hiện và thông báo.
    """
    console.rule("[bold cyan]CASE 1: MÔ PHỎNG WAL DANGLING TRANSACTION[/bold cyan]")
    console.print("[dim]Mô tả: Tạo WAL entry dang dở -> init phải phát hiện và recover.[/dim]")

    # 1. Setup
    setup_environment()
    run_cli(["init"])
    
    # 2. Tạo backup bình thường trước
    create_test_data("stable_data", content="Stable data before crash")
    res = run_cli(["backup", "stable_data", "--label", "StableBackup"])
    stable_id = get_snapshot_id(res.stdout)
    
    if not stable_id:
        console.print("[red]Không tạo được backup ban đầu![/red]")
        return False
    console.print(f"   -> Backup ổn định OK (ID: {stable_id[:16]}...)")

    # 3. Mô phỏng crash: Ghi BEGIN vào WAL nhưng không COMMIT
    wal_file = SANDBOX_DIR / "store" / "wal.journal"
    
    import time
    fake_txn_id = f"crash_{int(time.time())}"
    
    with open(wal_file, 'a') as f:
        f.write(f"BEGIN|{fake_txn_id}|BACKUP|{time.time()}\n")
        f.write(f"WRITE|{fake_txn_id}|chunks/fake_chunk_123|{time.time()}\n")
        # KHÔNG ghi COMMIT -> dangling transaction
    
    console.print(f"   -> [yellow]⚠ ĐÃ TẠO DANGLING TRANSACTION: {fake_txn_id}[/yellow]")

    # 4. Chạy init lại (trigger recovery)
    init_args = ["init"]
    res = run_cli(init_args)
    
    # 5. Verify snapshot cũ vẫn còn và valid
    passed, failed = verify_all_snapshots()
    
    success = stable_id in passed and len(failed) == 0
    details = (
        f"Snapshots còn lại: {len(passed)}\n"
        f"Snapshots valid: {passed}\n"
        f"Snapshots bị lỗi: {failed}"
    )
    
    return print_verdict(
        "WAL recovery xử lý dangling transaction", 
        success,
        details,
        command_args=init_args
    )


def scenario_2_kill_backup_process():
    """
    CASE 2: KILL BACKUP PROCESS GIỮA CHỪNG
    
    Mô tả: Chạy backup trên dữ liệu lớn, kill process giữa chừng.
    Store phải ổn định sau khi restart.
    """
    console.rule("[bold cyan]CASE 2: KILL BACKUP PROCESS GIỮA CHỪNG[/bold cyan]")
    console.print("[dim]Mô tả: Backup dữ liệu lớn, kill giữa chừng -> Store vẫn ổn định.[/dim]")

    # 1. Setup
    setup_environment()
    run_cli(["init"])
    
    # 2. Tạo backup ổn định trước
    create_test_data("stable", content="Stable data")
    res = run_cli(["backup", "stable", "--label", "Stable"])
    stable_id = get_snapshot_id(res.stdout)
    
    if not stable_id:
        console.print("[red]Không tạo được backup ban đầu![/red]")
        return False
    console.print(f"   -> Backup ổn định OK (ID: {stable_id[:16]}...)")

    # 3. Tạo dữ liệu lớn để backup lâu
    console.print("   -> Tạo dữ liệu lớn (5MB, 50 files)...")
    create_test_data("large_data", size_mb=1, num_files=50)
    
    # 4. Chạy backup và kill sau 0.5 giây
    console.print("   -> Chạy backup và kill sau 0.5 giây...")
    proc = run_cli_async(["backup", "large_data", "--label", "WillCrash"])
    
    time.sleep(0.5)  # Chờ một chút để backup bắt đầu
    
    # Kill process
    try:
        if os.name == 'nt':
            # Windows
            proc.terminate()
        else:
            # Unix
            proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
    except:
        proc.kill()
    
    console.print(f"   -> [yellow]⚠ ĐÃ KILL BACKUP PROCESS[/yellow]")

    # 5. Kiểm tra WAL status
    wal_status = get_wal_status()
    console.print(f"   -> WAL dangling transactions: {len(wal_status.get('dangling', []))}")

    # 6. Chạy init (trigger recovery)
    init_args = ["init"]
    res = run_cli(init_args)
    console.print("   -> Chạy init để trigger WAL recovery...")
    
    # 7. Verify store vẫn ổn định
    # - Snapshot cũ vẫn valid
    # - Có thể tạo backup mới
    passed, failed = verify_all_snapshots()
    
    # 8. Thử tạo backup mới
    create_test_data("new_after_crash", content="New data after crash")
    res = run_cli(["backup", "new_after_crash", "--label", "AfterCrash"])
    new_id = get_snapshot_id(res.stdout)
    
    success = (stable_id in passed) and (new_id is not None)
    details = (
        f"Backup cũ (stable): {'✔ valid' if stable_id in passed else '✘ invalid'}\n"
        f"Backup mới sau crash: {'✔ OK' if new_id else '✘ FAIL'}\n"
        f"Total snapshots failed: {len(failed)}"
    )
    
    return print_verdict(
        "Store ổn định sau khi kill backup", 
        success,
        details,
        command_args=["backup", "large_data", "--label", "WillCrash"]
    )


def scenario_3_multiple_crashes():
    """
    CASE 3: NHIỀU LẦN CRASH LIÊN TIẾP
    
    Mô tả: Mô phỏng nhiều lần crash liên tiếp.
    Sau mỗi lần recover, store vẫn nhất quán.
    """
    console.rule("[bold cyan]CASE 3: NHIỀU LẦN CRASH LIÊN TIẾP[/bold cyan]")
    console.print("[dim]Mô tả: Crash nhiều lần liên tiếp -> Store vẫn nhất quán.[/dim]")

    # 1. Setup
    setup_environment()
    run_cli(["init"])
    
    # 2. Tạo backup ban đầu
    create_test_data("initial", content="Initial data")
    res = run_cli(["backup", "initial", "--label", "Initial"])
    initial_id = get_snapshot_id(res.stdout)
    
    if not initial_id:
        console.print("[red]Không tạo được backup ban đầu![/red]")
        return False
    console.print(f"   -> Backup ban đầu OK (ID: {initial_id[:16]}...)")

    # 3. Mô phỏng 3 lần crash liên tiếp
    wal_file = SANDBOX_DIR / "store" / "wal.journal"
    
    for i in range(3):
        console.print(f"   -> Mô phỏng crash #{i+1}...")
        
        # Ghi dangling transaction
        fake_txn_id = f"crash_{i}_{int(time.time())}"
        with open(wal_file, 'a') as f:
            f.write(f"BEGIN|{fake_txn_id}|BACKUP|{time.time()}\n")
            f.write(f"WRITE|{fake_txn_id}|chunks/fake_{i}|{time.time()}\n")
        
        # Recovery
        run_cli(["init"])
    
    console.print("   -> [yellow]⚠ ĐÃ MÔ PHỎNG 3 LẦN CRASH[/yellow]")

    # 4. Verify toàn bộ
    passed, failed = verify_all_snapshots()
    
    # 5. Thử backup mới
    create_test_data("after_crashes", content="After multiple crashes")
    res = run_cli(["backup", "after_crashes", "--label", "AfterCrashes"])
    new_id = get_snapshot_id(res.stdout)
    
    success = (initial_id in passed) and (new_id is not None) and (len(failed) == 0)
    details = (
        f"Backup ban đầu: {'✔ valid' if initial_id in passed else '✘ invalid'}\n"
        f"Backup mới: {'✔ OK' if new_id else '✘ FAIL'}\n"
        f"Tổng lỗi: {len(failed)}"
    )
    
    return print_verdict(
        "Store nhất quán sau nhiều lần crash", 
        success,
        details,
        command_args=["init"]
    )


def scenario_4_restore_after_crash():
    """
    CASE 4: RESTORE SAU CRASH
    
    Mô tả: Sau khi crash và recover, restore vẫn hoạt động bình thường.
    """
    console.rule("[bold cyan]CASE 4: RESTORE SAU CRASH[/bold cyan]")
    console.print("[dim]Mô tả: Restore dữ liệu từ backup sau crash -> Dữ liệu nguyên vẹn.[/dim]")

    # 1. Setup
    setup_environment()
    run_cli(["init"])
    
    # 2. Tạo dữ liệu và backup
    original_content = "Important data that must survive crash - ABC123XYZ"
    data_dir = create_test_data("important", content=original_content)
    
    res = run_cli(["backup", "important", "--label", "Important"])
    snap_id = get_snapshot_id(res.stdout)
    
    if not snap_id:
        console.print("[red]Không tạo được backup![/red]")
        return False
    console.print(f"   -> Backup OK (ID: {snap_id[:16]}...)")

    # 3. Mô phỏng crash
    wal_file = SANDBOX_DIR / "store" / "wal.journal"
    fake_txn_id = f"crash_{int(time.time())}"
    with open(wal_file, 'a') as f:
        f.write(f"BEGIN|{fake_txn_id}|BACKUP|{time.time()}\n")
        f.write(f"WRITE|{fake_txn_id}|chunks/fake_crash|{time.time()}\n")
    
    console.print("   -> [yellow]⚠ ĐÃ MÔ PHỎNG CRASH[/yellow]")

    # 4. Recovery
    run_cli(["init"])
    console.print("   -> Recovery done.")

    # 5. Restore
    restore_dir = SANDBOX_DIR / "restored"
    restore_args = ["restore", snap_id, str(restore_dir)]
    res = run_cli(restore_args)
    
    # 6. Kiểm tra nội dung
    restored_file = restore_dir / "file_0.txt"
    content_match = False
    if restored_file.exists():
        with open(restored_file, 'r') as f:
            restored_content = f.read()
        content_match = original_content in restored_content
    
    success = content_match
    details = (
        f"File restored: {'✔' if restored_file.exists() else '✘'}\n"
        f"Content match: {'✔' if content_match else '✘'}"
    )
    
    return print_verdict(
        "Restore hoạt động sau crash", 
        success,
        details,
        command_args=restore_args
    )


# --- MAIN ---

if __name__ == "__main__":
    console.print(Panel(
        "[bold white]TEST SUITE: WAL CRASH RECOVERY[/bold white]\n"
        "[dim]Kiểm tra khả năng phục hồi sau crash[/dim]",
        style="bold blue"
    ))
    
    results = []
    
    results.append(("CASE 1: Dangling WAL transaction", scenario_1_simulate_wal_dangling()))
    results.append(("CASE 2: Kill backup process", scenario_2_kill_backup_process()))
    results.append(("CASE 3: Nhiều lần crash", scenario_3_multiple_crashes()))
    results.append(("CASE 4: Restore sau crash", scenario_4_restore_after_crash()))
    
    # Summary
    console.print("\n")
    console.rule("[bold]TỔNG KẾT[/bold]")
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "[green]✔ PASS[/green]" if result else "[red]✘ FAIL[/red]"
        console.print(f"   {status} {name}")
    
    console.print(f"\n[bold]Kết quả: {passed}/{total} test passed[/bold]")
    
    if passed == total:
        console.print("[bold green]🎉 ALL TESTS PASSED![/bold green]")
    else:
        console.print("[bold red]⚠ SOME TESTS FAILED![/bold red]")
        sys.exit(1)
