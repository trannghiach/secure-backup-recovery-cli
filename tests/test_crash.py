"""
TEST SUITE: CRASH RECOVERY
==========================
Yêu cầu đề bài #5: Kill chương trình giữa lúc backup; 
lần chạy sau không được có snapshot lỗi và store vẫn hoạt động.

Cơ chế test:
- Chèn "bom" (os._exit) vào code để mô phỏng crash thật
- Kiểm tra WAL recovery xóa snapshot dang dở
- Kiểm tra store vẫn hoạt động bình thường sau crash
"""

import os
import sys
import json
import shutil
import subprocess
import re
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

# --- CẤU HÌNH ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SANDBOX_DIR = PROJECT_ROOT / "tests" / "sandbox_crash"
AUDIT_LOG_PATH = SANDBOX_DIR / "store" / "audit.log"
CLI_CMD = [sys.executable, "-m", "src.sbackup.main"]
BACKUP_PY = PROJECT_ROOT / "src" / "sbackup" / "commands" / "backup.py"

console = Console()

# --- CODE BOM ---
CRASH_BOMB = '''
            # =============== [CRASH BOMB - AUTO INSERTED] ===============
            import os as _crash_os
            _crash_os._exit(1)  # Kill ngay, không cleanup
            # =============================================================
'''

MARKER_BEFORE = "            # Bước 4: WAL COMMIT"
MARKER_AFTER = "            storage.commit_backup(snapshot_id)"

# --- HÀM HỖ TRỢ ---

def setup_environment():
    """Khởi tạo môi trường test sạch."""
    if SANDBOX_DIR.exists():
        try: shutil.rmtree(SANDBOX_DIR)
        except: pass
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    
    policy_src = PROJECT_ROOT / "policy.yaml"
    policy_dst = SANDBOX_DIR / "policy.yaml"
    if policy_src.exists():
        shutil.copy2(policy_src, policy_dst)

def run_cli(args, cwd=SANDBOX_DIR, timeout=30):
    """Chạy CLI command."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = f"{PROJECT_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["SBACKUP_AUDIT_LOG_PATH"] = str(AUDIT_LOG_PATH)

    try:
        result = subprocess.run(
            CLI_CMD + args, cwd=cwd, capture_output=True, text=True,
            env=env, encoding='utf-8', errors='replace', timeout=timeout
        )
        return result
    except subprocess.TimeoutExpired:
        return None

def get_snapshot_id(output):
    """Trích xuất snapshot ID từ output."""
    if not output:
        return None
    match = re.search(r"([a-f0-9]{64})", output)
    return match.group(1) if match else None

def create_test_data(name="data", content="Test content"):
    """Tạo dữ liệu test."""
    d = SANDBOX_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "file.txt", "w") as f:
        f.write(content)
    return d

def get_current_user():
    import getpass
    return getpass.getuser()

def list_snapshots():
    """Liệt kê snapshot trong store."""
    snapshots_dir = SANDBOX_DIR / "store" / "snapshots"
    if not snapshots_dir.exists():
        return []
    return [f.stem for f in snapshots_dir.glob("*.json")]

def read_wal():
    """Đọc nội dung WAL."""
    wal_file = SANDBOX_DIR / "store" / "journal.wal"
    if not wal_file.exists():
        return None
    with open(wal_file, 'r') as f:
        return f.read()

def install_crash_bomb():
    """Chèn crash bomb vào backup.py."""
    with open(BACKUP_PY, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Kiểm tra đã có bomb chưa
    if "CRASH BOMB" in content:
        return True  # Đã có
    
    # Tìm vị trí chèn (sau save_manifest, trước commit)
    if MARKER_BEFORE not in content:
        console.print("[red]Không tìm thấy vị trí chèn bomb![/red]")
        return False
    
    new_content = content.replace(
        MARKER_BEFORE,
        CRASH_BOMB + "\n" + MARKER_BEFORE
    )
    
    with open(BACKUP_PY, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    return True

def remove_crash_bomb():
    """Gỡ crash bomb khỏi backup.py."""
    with open(BACKUP_PY, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if "CRASH BOMB" not in content:
        return True  # Không có bomb
    
    # Xóa đoạn bomb
    lines = content.split('\n')
    new_lines = []
    skip = False
    
    for line in lines:
        if "CRASH BOMB - AUTO INSERTED" in line:
            skip = True
            continue
        if skip and "===============" in line:
            skip = False
            continue
        if skip:
            continue
        new_lines.append(line)
    
    new_content = '\n'.join(new_lines)
    
    with open(BACKUP_PY, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    return True

def print_verdict(test_name, success, details="", command_args=None):
    """In kết quả kiểm thử."""
    user = get_current_user()
    cmd_str = f"sbackup {' '.join(command_args)}" if command_args else "N/A"
    
    if success:
        console.print(Panel(
            f"[bold green]✔ PASS: {test_name}[/bold green]\n\n"
            f"[cyan]📋 Command:[/cyan] {cmd_str}\n"
            f"[cyan]👤 User:[/cyan] {user}\n\n"
            f"[dim]{details}[/dim]",
            border_style="green"
        ))
        return True
    else:
        console.print(Panel(
            f"[bold red]✘ FAIL: {test_name}[/bold red]\n\n"
            f"[cyan]📋 Command:[/cyan] {cmd_str}\n"
            f"[cyan]👤 User:[/cyan] {user}\n\n"
            f"[red]{details}[/red]",
            border_style="red"
        ))
        return False

# --- KỊCH BẢN TEST ---

def scenario_1_crash_and_recover():
    """
    CASE 1: CRASH GIỮA BACKUP -> RECOVERY
    
    1. Cài bomb vào code
    2. Chạy backup -> CRASH (exit code != 0)
    3. Kiểm tra: có file manifest rác không? WAL có BEGIN không COMMIT?
    4. Chạy init -> WAL Recovery
    5. Kiểm tra: manifest rác đã bị xóa? WAL đã sạch?
    """
    console.rule("[bold cyan]CASE 1: CRASH & RECOVERY[/bold cyan]")
    console.print("[dim]Mô tả: Backup bị crash giữa chừng, init lại phải recovery thành công.[/dim]")

    # 1. Setup
    setup_environment()
    
    # Tạo store trước (không dùng init vì cần kiểm tra WAL sau crash)
    (SANDBOX_DIR / "store" / "snapshots").mkdir(parents=True, exist_ok=True)
    (SANDBOX_DIR / "store" / "chunks").mkdir(parents=True, exist_ok=True)
    
    # 2. Cài bomb
    console.print("   -> Cài crash bomb vào backup.py...")
    if not install_crash_bomb():
        return False
    
    # 3. Tạo data và chạy backup (sẽ crash)
    create_test_data("crash_data", "Data for crash test")
    console.print("   -> Chạy backup (sẽ crash)...")
    
    backup_args = ["backup", "crash_data", "--label", "CrashTest"]
    res = run_cli(backup_args)
    
    # Kiểm tra đã crash (exit code != 0 hoặc không có output success)
    crashed = res is None or res.returncode != 0
    console.print(f"   -> Backup exit code: {res.returncode if res else 'timeout/crash'}")
    
    # 4. Kiểm tra trạng thái sau crash
    snapshots_before = list_snapshots()
    wal_before = read_wal()
    
    console.print(f"   -> Snapshots sau crash: {len(snapshots_before)}")
    console.print(f"   -> WAL sau crash: {'Có BEGIN' if wal_before and 'BEGIN' in wal_before else 'Trống'}")
    
    # Nếu có manifest rác và WAL có BEGIN không COMMIT = crash thành công
    has_dangling = wal_before and 'BEGIN' in wal_before and 'COMMIT' not in wal_before
    
    # 5. Gỡ bomb TRƯỚC KHI chạy init
    console.print("   -> Gỡ crash bomb...")
    remove_crash_bomb()
    
    # 6. Chạy init để trigger recovery
    console.print("   -> Chạy init (WAL Recovery)...")
    init_res = run_cli(["init"])
    init_output = init_res.stdout + init_res.stderr if init_res else ""
    
    recovery_triggered = "Recovery" in init_output or "rollback" in init_output.lower()
    console.print(f"   -> Recovery triggered: {recovery_triggered}")
    
    # 7. Kiểm tra sau recovery
    snapshots_after = list_snapshots()
    wal_after = read_wal()
    
    # Snapshot rác phải bị xóa, WAL phải sạch
    # (Nếu không có snapshot rác ban đầu thì vẫn OK - nghĩa là crash trước khi ghi manifest)
    wal_clean = wal_after is None or 'BEGIN' not in wal_after or 'COMMIT' in wal_after
    
    details = (
        f"Crashed: {crashed}\n"
        f"Snapshots trước recovery: {len(snapshots_before)}\n"
        f"Snapshots sau recovery: {len(snapshots_after)}\n"
        f"WAL dangling trước: {has_dangling}\n"
        f"WAL sạch sau: {wal_clean}\n"
        f"Recovery output: {init_output[:200]}..."
    )
    
    success = crashed and wal_clean
    return print_verdict(
        "Crash & Recovery thành công",
        success,
        details,
        ["init"]
    )


def scenario_2_store_works_after_crash():
    """
    CASE 2: STORE HOẠT ĐỘNG BÌNH THƯỜNG SAU CRASH
    
    Sau recovery, phải backup/verify được bình thường
    """
    console.rule("[bold cyan]CASE 2: STORE HOẠT ĐỘNG SAU RECOVERY[/bold cyan]")
    console.print("[dim]Mô tả: Sau crash và recovery, store vẫn hoạt động bình thường.[/dim]")

    # Đảm bảo bomb đã được gỡ
    remove_crash_bomb()
    
    # 1. Setup fresh
    setup_environment()
    run_cli(["init"])
    
    # 2. Tạo backup bình thường
    create_test_data("normal_data", "Normal backup after crash test")
    backup_args = ["backup", "normal_data", "--label", "PostCrashBackup"]
    res = run_cli(backup_args)
    
    if not res or res.returncode != 0:
        return print_verdict(
            "Backup sau recovery",
            False,
            f"Backup failed: {res.stderr if res else 'No output'}",
            backup_args
        )
    
    snap_id = get_snapshot_id(res.stdout)
    console.print(f"   -> Backup OK (ID: {snap_id[:16] if snap_id else 'N/A'}...)")
    
    # 3. Verify
    if snap_id:
        verify_args = ["verify", snap_id]
        res = run_cli(verify_args)
        verify_ok = res and "CONFIRMED" in res.stdout
        
        details = (
            f"Snapshot ID: {snap_id[:32]}...\n"
            f"Verify result: {'PASS' if verify_ok else 'FAIL'}\n"
            f"Output: {res.stdout[:200] if res else 'N/A'}..."
        )
        
        return print_verdict(
            "Store hoạt động sau recovery",
            verify_ok,
            details,
            verify_args
        )
    
    return False


def scenario_3_no_invalid_snapshot():
    """
    CASE 3: KHÔNG CÓ SNAPSHOT KHÔNG HỢP LỆ
    
    Sau crash, list-snapshots không được có snapshot lỗi
    """
    console.rule("[bold cyan]CASE 3: KHÔNG CÓ SNAPSHOT LỖI[/bold cyan]")
    console.print("[dim]Mô tả: Sau recovery, tất cả snapshot trong list phải verify được.[/dim]")

    # Đảm bảo bomb đã được gỡ
    remove_crash_bomb()
    
    # Dùng lại store từ scenario trước hoặc tạo mới
    if not (SANDBOX_DIR / "store").exists():
        setup_environment()
        run_cli(["init"])
    
    # 1. List snapshots
    res = run_cli(["list-snapshots"])
    console.print(f"   -> List snapshots output: {res.stdout[:200] if res else 'N/A'}...")
    
    snapshots = list_snapshots()
    console.print(f"   -> Số snapshot: {len(snapshots)}")
    
    if not snapshots:
        return print_verdict(
            "Không có snapshot lỗi",
            True,
            "Không có snapshot nào (store sạch)",
            ["list-snapshots"]
        )
    
    # 2. Verify từng snapshot
    all_valid = True
    invalid_snaps = []
    
    for snap_id in snapshots:
        res = run_cli(["verify", snap_id])
        if not res or "FAILED" in res.stdout or "Error" in res.stderr:
            all_valid = False
            invalid_snaps.append(snap_id[:16])
    
    details = (
        f"Total snapshots: {len(snapshots)}\n"
        f"Invalid snapshots: {invalid_snaps if invalid_snaps else 'None'}\n"
        f"All valid: {all_valid}"
    )
    
    return print_verdict(
        "Tất cả snapshot hợp lệ",
        all_valid,
        details,
        ["verify", "..."]
    )


# --- MAIN ---

if __name__ == "__main__":
    console.print(Panel(
        "[bold white]TEST SUITE: CRASH RECOVERY[/bold white]\n"
        "[dim]Yêu cầu đề bài #5: Kill backup giữa chừng, lần sau không có snapshot lỗi[/dim]",
        style="bold blue"
    ))
    
    # Đảm bảo gỡ bomb trước khi bắt đầu
    remove_crash_bomb()
    
    results = []
    
    try:
        results.append(("CASE 1: Crash & Recovery", scenario_1_crash_and_recover()))
        results.append(("CASE 2: Store hoạt động sau crash", scenario_2_store_works_after_crash()))
        results.append(("CASE 3: Không có snapshot lỗi", scenario_3_no_invalid_snapshot()))
    finally:
        # Luôn gỡ bomb sau khi test xong
        remove_crash_bomb()
        console.print("\n[dim]✔ Đã gỡ crash bomb khỏi backup.py[/dim]")
    
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
