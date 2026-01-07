"""
TEST SUITE: WAL ROLLBACK DETECTION
===================================
Kiểm tra khả năng phát hiện tráo đổi/giả mạo snapshot.

Kịch bản tấn công:
- Attacker tráo đổi tên file snapshot cũ thành mới
- Attacker copy snapshot cũ và đổi tên thành ID khác
- Hệ thống phải phát hiện sự không nhất quán
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
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # real_test -> tests -> LabCLI
SANDBOX_DIR = PROJECT_ROOT / "tests" / "sandbox_rollback"
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
    
    # Copy policy.yaml vào sandbox
    policy_src = PROJECT_ROOT / "policy.yaml"
    policy_dst = SANDBOX_DIR / "policy.yaml"
    if policy_src.exists():
        shutil.copy2(policy_src, policy_dst)

def run_cli(args, cwd=SANDBOX_DIR):
    """Chạy CLI command."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = f"{PROJECT_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["SBACKUP_AUDIT_LOG_PATH"] = str(AUDIT_LOG_PATH)

    result = subprocess.run(
        CLI_CMD + args, cwd=cwd, capture_output=True, text=True,
        env=env, encoding='utf-8', errors='replace'
    )
    return result

def get_snapshot_id(output):
    """Trích xuất snapshot ID từ output."""
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
    """Lấy tên user hiện tại."""
    import getpass
    return getpass.getuser()

def extract_error_text(output):
    """Lọc thông báo lỗi từ CLI."""
    keywords = ["Mismatch", "FAILED", "không khớp", "CẢNH BÁO", "Missing", "tampered", "invalid", "corrupted", "not found"]
    clean = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])').sub('', output)
    error_lines = []
    for line in clean.splitlines():
        if any(k.lower() in line.lower() for k in keywords):
            cleaned_line = line.strip().strip("│┌┐└┘─ ")
            if cleaned_line:
                error_lines.append(cleaned_line)
    return "\n".join(error_lines) if error_lines else "Không tìm thấy chi tiết lỗi."

def print_verdict(test_name, output, expect_fail=True, command_args=None, snap_id=None):
    """In kết quả kiểm thử."""
    has_error = any(k in output for k in ["FAILED", "Mismatch", "not found", "Error", "DENY"])
    
    user = get_current_user()
    cmd_str = f"sbackup {' '.join(command_args)}" if command_args else "N/A"
    
    if expect_fail:
        if has_error:
            msg = extract_error_text(output)
            console.print(Panel(
                f"[bold green]✔ PASS: {test_name}[/bold green]\n\n"
                f"[cyan]📋 Command đã chạy:[/cyan] [white]{cmd_str}[/white]\n"
                f"[cyan]👤 User thực thi:[/cyan] [white]{user}[/white]\n"
                f"[cyan]🔑 Snapshot ID:[/cyan] [white]{snap_id if snap_id else 'N/A'}[/white]\n\n"
                f"[bold yellow]🔍 Hệ thống đã phát hiện:[/bold yellow]\n[yellow]{msg}[/yellow]\n\n"
                f"[dim]📊 Chi tiết output:[/dim]\n[dim]{output[:500]}{'...' if len(output) > 500 else ''}[/dim]",
                border_style="green",
                title="[bold]KẾT QUẢ KIỂM THỬ[/bold]"
            ))
            return True
        else:
            console.print(Panel(
                f"[bold red]✘ FAIL: {test_name}[/bold red]\n\n"
                f"[cyan]📋 Command đã chạy:[/cyan] [white]{cmd_str}[/white]\n"
                f"[cyan]👤 User thực thi:[/cyan] [white]{user}[/white]\n\n"
                "[bold red]⚠️ Hệ thống KHÔNG phát hiện sự thay đổi![/bold red]\n\n"
                f"[dim]📊 Output nhận được:[/dim]\n[dim]{output[:500]}{'...' if len(output) > 500 else ''}[/dim]",
                border_style="red",
                title="[bold]KẾT QUẢ KIỂM THỬ[/bold]"
            ))
            return False
    else:
        # Expect success
        if not has_error:
            console.print(Panel(
                f"[bold green]✔ PASS: {test_name}[/bold green]\n\n"
                f"[cyan]📋 Command đã chạy:[/cyan] [white]{cmd_str}[/white]\n"
                f"[cyan]👤 User thực thi:[/cyan] [white]{user}[/white]",
                border_style="green"
            ))
            return True
        else:
            console.print(Panel(
                f"[bold red]✘ FAIL: {test_name}[/bold red]\n\n"
                f"[cyan]📋 Command đã chạy:[/cyan] [white]{cmd_str}[/white]\n"
                f"Output: {output[:300]}",
                border_style="red"
            ))
            return False

# --- KỊCH BẢN TẤN CÔNG ---

def scenario_1_swap_snapshot_name():
    """
    CASE 1: TRÁO ĐỔI TÊN FILE SNAPSHOT
    
    Mô tả: Attacker tạo 2 bản backup khác nhau, sau đó tráo đổi tên file.
    Khi verify snapshot A, nội dung thực tế là của snapshot B.
    Hệ thống phải phát hiện Merkle Root không khớp.
    """
    console.rule("[bold cyan]CASE 1: TRÁO ĐỔI TÊN FILE SNAPSHOT[/bold cyan]")
    console.print("[dim]Mô tả: Tráo đổi tên file snapshot A <-> B. Verify phải phát hiện Merkle Root không khớp với ID.[/dim]")

    # 1. Setup
    setup_environment()
    run_cli(["init"])
    
    # 2. Tạo 2 bản backup với nội dung khác nhau
    create_test_data("data_v1", "Version 1 - Original content ABC")
    res1 = run_cli(["backup", "data_v1", "--label", "Version1"])
    snap_id_1 = get_snapshot_id(res1.stdout)
    
    if not snap_id_1:
        console.print("[red]Không tạo được backup 1![/red]")
        return False
    console.print(f"   -> Backup 1 OK (ID: {snap_id_1[:16]}...)")
    
    # Tạo nội dung khác
    create_test_data("data_v2", "Version 2 - COMPLETELY DIFFERENT XYZ 12345")
    res2 = run_cli(["backup", "data_v2", "--label", "Version2"])
    snap_id_2 = get_snapshot_id(res2.stdout)
    
    if not snap_id_2:
        console.print("[red]Không tạo được backup 2![/red]")
        return False
    console.print(f"   -> Backup 2 OK (ID: {snap_id_2[:16]}...)")
    
    # 3. Tráo đổi tên file snapshot
    snapshots_dir = SANDBOX_DIR / "store" / "snapshots"
    file_1 = snapshots_dir / f"{snap_id_1}.json"
    file_2 = snapshots_dir / f"{snap_id_2}.json"
    temp_file = snapshots_dir / "temp_swap.json"
    
    # Swap: A -> temp, B -> A, temp -> B
    shutil.move(file_1, temp_file)
    shutil.move(file_2, file_1)
    shutil.move(temp_file, file_2)
    
    console.print(f"   -> [yellow]⚠ ĐÃ TRÁO ĐỔI: {snap_id_1[:8]}... <-> {snap_id_2[:8]}...[/yellow]")

    # 4. Verify snapshot 1 (nội dung thực tế là của snapshot 2)
    console.print("   -> Chạy Verify trên snapshot đã bị tráo...")
    verify_args = ["verify", snap_id_1]
    res = run_cli(verify_args)
    output = res.stdout + res.stderr
    
    return print_verdict(
        "Phát hiện tráo đổi snapshot (Merkle mismatch)", 
        output, 
        expect_fail=True,
        command_args=verify_args, 
        snap_id=snap_id_1
    )


def scenario_2_copy_and_rename():
    """
    CASE 2: SAO CHÉP VÀ ĐỔI TÊN SNAPSHOT
    
    Mô tả: Attacker copy file snapshot cũ, đổi snapshot_id bên trong JSON
    để giả mạo thành một snapshot khác.
    Hệ thống phải phát hiện snapshot_id không khớp với filename/Merkle.
    """
    console.rule("[bold cyan]CASE 2: COPY & RENAME SNAPSHOT (Forgery)[/bold cyan]")
    console.print("[dim]Mô tả: Copy snapshot cũ, sửa snapshot_id trong JSON -> Hệ thống phải reject.[/dim]")

    # 1. Setup
    setup_environment()
    run_cli(["init"])
    
    # 2. Tạo backup gốc
    create_test_data("original", "Original data for forgery test")
    res = run_cli(["backup", "original", "--label", "OriginalBackup"])
    original_id = get_snapshot_id(res.stdout)
    
    if not original_id:
        console.print("[red]Không tạo được backup![/red]")
        return False
    console.print(f"   -> Backup gốc OK (ID: {original_id[:16]}...)")
    
    # 3. Copy và tạo snapshot giả
    snapshots_dir = SANDBOX_DIR / "store" / "snapshots"
    original_file = snapshots_dir / f"{original_id}.json"
    
    # Tạo fake ID
    fake_id = "f" * 64  # ID giả toàn chữ 'f'
    fake_file = snapshots_dir / f"{fake_id}.json"
    
    # Đọc và sửa JSON
    with open(original_file, 'r') as f:
        data = json.load(f)
    
    # Sửa snapshot_id thành fake (giữ nguyên merkle_root và content)
    data['snapshot_id'] = fake_id
    
    with open(fake_file, 'w') as f:
        json.dump(data, f)
    
    console.print(f"   -> [yellow]⚠ ĐÃ TẠO SNAPSHOT GIẢ: {fake_id[:16]}...[/yellow]")

    # 4. Verify snapshot giả
    console.print("   -> Chạy Verify trên snapshot giả mạo...")
    verify_args = ["verify", fake_id]
    res = run_cli(verify_args)
    output = res.stdout + res.stderr
    
    return print_verdict(
        "Phát hiện snapshot giả mạo (ID không khớp Merkle)", 
        output, 
        expect_fail=True,
        command_args=verify_args, 
        snap_id=fake_id
    )


def scenario_3_modify_snapshot_id_in_json():
    """
    CASE 3: SỬA SNAPSHOT_ID TRONG JSON
    
    Mô tả: Attacker sửa trực tiếp trường snapshot_id trong file JSON,
    nhưng giữ nguyên filename. Verify phải phát hiện.
    """
    console.rule("[bold cyan]CASE 3: SỬA SNAPSHOT_ID TRONG JSON[/bold cyan]")
    console.print("[dim]Mô tả: Sửa snapshot_id trong JSON thành giá trị khác, filename giữ nguyên.[/dim]")

    # 1. Setup
    setup_environment()
    run_cli(["init"])
    
    # 2. Tạo backup
    create_test_data("test_data", "Content for ID tampering test")
    res = run_cli(["backup", "test_data", "--label", "IDTest"])
    snap_id = get_snapshot_id(res.stdout)
    
    if not snap_id:
        console.print("[red]Không tạo được backup![/red]")
        return False
    console.print(f"   -> Backup OK (ID: {snap_id[:16]}...)")
    
    # 3. Sửa snapshot_id trong JSON
    snapshots_dir = SANDBOX_DIR / "store" / "snapshots"
    manifest_file = snapshots_dir / f"{snap_id}.json"
    
    with open(manifest_file, 'r') as f:
        data = json.load(f)
    
    original_snap_id = data['snapshot_id']
    data['snapshot_id'] = "a" * 64  # Sửa thành ID giả
    
    with open(manifest_file, 'w') as f:
        json.dump(data, f)
    
    console.print(f"   -> [yellow]⚠ ĐÃ SỬA snapshot_id: {original_snap_id[:8]}... -> aaaa...[/yellow]")

    # 4. Verify
    console.print("   -> Chạy Verify...")
    verify_args = ["verify", snap_id]
    res = run_cli(verify_args)
    output = res.stdout + res.stderr
    
    return print_verdict(
        "Phát hiện snapshot_id bị sửa đổi", 
        output, 
        expect_fail=True,
        command_args=verify_args, 
        snap_id=snap_id
    )


# --- MAIN ---

if __name__ == "__main__":
    console.print(Panel(
        "[bold white]TEST SUITE: WAL ROLLBACK DETECTION[/bold white]\n"
        "[dim]Kiểm tra khả năng phát hiện tráo đổi/giả mạo snapshot[/dim]",
        style="bold blue"
    ))
    
    results = []
    
    results.append(("CASE 1: Tráo đổi tên file", scenario_1_swap_snapshot_name()))
    results.append(("CASE 2: Copy & Rename", scenario_2_copy_and_rename()))
    results.append(("CASE 3: Sửa snapshot_id", scenario_3_modify_snapshot_id_in_json()))
    
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
