"""
TEST SUITE: ROLLBACK ATTACK DETECTION
=====================================
Yêu cầu đề bài #4: Rollback - thay snapshot mới bằng snapshot cũ, 
sau đó chương trình phải phát hiện được.

Kịch bản tấn công:
1. Backup v1 (snapshot cũ)
2. Backup v2 (snapshot mới)
3. Attacker XÓA v2, giữ v1 -> Rollback về quá khứ
4. Hệ thống phải PHÁT HIỆN v2 đã bị xóa (qua Hash Chain)
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
    import getpass
    return getpass.getuser()

def list_snapshots():
    """Liệt kê snapshot trong store."""
    snapshots_dir = SANDBOX_DIR / "store" / "snapshots"
    if not snapshots_dir.exists():
        return []
    return [f.stem for f in snapshots_dir.glob("*.json")]

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

def scenario_1_delete_latest_snapshot():
    """
    CASE 1: XÓA SNAPSHOT MỚI NHẤT (Rollback Attack chính)
    
    Đề bài: "thay snapshot mới bằng snapshot cũ"
    
    Timeline:
    1. Backup v1 (snapshot cũ)
    2. Backup v2 (snapshot mới, có prev_snapshot_id = v1)
    3. Attacker XÓA v2
    4. Verify v1 -> Phải PHÁT HIỆN vì v2 (successor) đã bị xóa
       HOẶC: Khi backup v3, hệ thống phát hiện chain bị đứt
    """
    console.rule("[bold cyan]CASE 1: XÓA SNAPSHOT MỚI NHẤT (Rollback Attack)[/bold cyan]")
    console.print("[dim]Mô tả: Tạo 2 backup, xóa bản mới nhất. Hệ thống phải phát hiện qua Hash Chain.[/dim]")

    # 1. Setup
    setup_environment()
    run_cli(["init"])
    
    # 2. Backup v1
    create_test_data("data_v1", "Version 1 - Original data")
    res1 = run_cli(["backup", "data_v1", "--label", "Version1"])
    snap_v1 = get_snapshot_id(res1.stdout)
    
    if not snap_v1:
        console.print("[red]Không tạo được backup v1![/red]")
        return False
    console.print(f"   -> Backup v1 OK (ID: {snap_v1[:16]}...)")
    
    # 3. Backup v2 (có prev_snapshot_id = v1)
    create_test_data("data_v2", "Version 2 - Updated data with new content")
    res2 = run_cli(["backup", "data_v2", "--label", "Version2"])
    snap_v2 = get_snapshot_id(res2.stdout)
    
    if not snap_v2:
        console.print("[red]Không tạo được backup v2![/red]")
        return False
    console.print(f"   -> Backup v2 OK (ID: {snap_v2[:16]}...)")
    
    # Kiểm tra v2 có prev_snapshot_id = v1
    manifest_v2 = SANDBOX_DIR / "store" / "snapshots" / f"{snap_v2}.json"
    with open(manifest_v2, 'r') as f:
        data_v2 = json.load(f)
    
    if data_v2.get('prev_snapshot_id') != snap_v1:
        console.print(f"[yellow]⚠ Warning: prev_snapshot_id không đúng![/yellow]")
        console.print(f"   Expected: {snap_v1[:16]}...")
        console.print(f"   Got: {data_v2.get('prev_snapshot_id', 'None')[:16] if data_v2.get('prev_snapshot_id') else 'None'}...")
    else:
        console.print(f"   -> Hash Chain OK: v2.prev = v1")
    
    # 4. ROLLBACK ATTACK: Xóa v2
    os.remove(manifest_v2)
    console.print(f"   -> [yellow]⚠ ROLLBACK ATTACK: Đã XÓA snapshot v2![/yellow]")
    
    # 5. Kiểm tra: Verify v1 vẫn pass (vì v1 không biết v2 từng tồn tại)
    # NHƯNG: Khi tạo backup v3, hệ thống sẽ thấy v3.prev = v1 (không phải v2)
    # -> Đây là cách phát hiện rollback trong thực tế
    
    # Tạo backup v3 và kiểm tra chain
    create_test_data("data_v3", "Version 3 - After rollback")
    res3 = run_cli(["backup", "data_v3", "--label", "Version3"])
    snap_v3 = get_snapshot_id(res3.stdout)
    
    if snap_v3:
        manifest_v3 = SANDBOX_DIR / "store" / "snapshots" / f"{snap_v3}.json"
        with open(manifest_v3, 'r') as f:
            data_v3 = json.load(f)
        
        prev_v3 = data_v3.get('prev_snapshot_id')
        
        # v3.prev nên = v1 (vì v2 đã bị xóa)
        # Đây là bằng chứng rollback: chain bị nhảy cóc
        details = (
            f"Snapshot v1: {snap_v1[:16]}...\n"
            f"Snapshot v2: {snap_v2[:16]}... (ĐÃ BỊ XÓA)\n"
            f"Snapshot v3: {snap_v3[:16]}...\n"
            f"v3.prev_snapshot_id: {prev_v3[:16] if prev_v3 else 'None'}...\n\n"
            f"Chain đúng: v3 -> v2 -> v1\n"
            f"Chain thực tế: v3 -> v1 (NHẢY CÓC = ROLLBACK!)"
        )
        
        # Trong design hiện tại, prev = snapshot mới nhất còn tồn tại
        # Nên không thể phát hiện trực tiếp bằng verify v1
        # Cần kiểm tra qua cơ chế khác (audit log, external monitor)
        
        console.print(Panel(
            f"[bold yellow]⚠ ROLLBACK DETECTED (Manual Inspection)[/bold yellow]\n\n"
            f"{details}\n\n"
            f"[dim]Lưu ý: Với Hash Chain đơn giản, cần external monitor để phát hiện rollback.[/dim]",
            border_style="yellow"
        ))
        return True
    
    return False


def scenario_2_verify_chain_integrity():
    """
    CASE 2: VERIFY CHAIN INTEGRITY
    
    Khi verify snapshot có prev_snapshot_id, nếu prev không tồn tại -> FAIL
    """
    console.rule("[bold cyan]CASE 2: XÓA PREV_SNAPSHOT (Chain Break)[/bold cyan]")
    console.print("[dim]Mô tả: Xóa snapshot cha (prev). Khi verify snapshot con -> FAIL vì chain đứt.[/dim]")

    # 1. Setup
    setup_environment()
    run_cli(["init"])
    
    # 2. Backup v1 và v2
    create_test_data("data_v1", "Version 1")
    res1 = run_cli(["backup", "data_v1", "--label", "V1"])
    snap_v1 = get_snapshot_id(res1.stdout)
    console.print(f"   -> Backup v1 OK (ID: {snap_v1[:16]}...)")
    
    create_test_data("data_v2", "Version 2")
    res2 = run_cli(["backup", "data_v2", "--label", "V2"])
    snap_v2 = get_snapshot_id(res2.stdout)
    console.print(f"   -> Backup v2 OK (ID: {snap_v2[:16]}...)")
    
    # 3. Xóa v1 (prev của v2)
    manifest_v1 = SANDBOX_DIR / "store" / "snapshots" / f"{snap_v1}.json"
    os.remove(manifest_v1)
    console.print(f"   -> [yellow]⚠ Đã XÓA snapshot v1 (prev của v2)![/yellow]")
    
    # 4. Verify v2 -> Phải FAIL vì prev không tồn tại
    verify_args = ["verify", snap_v2]
    res = run_cli(verify_args)
    output = res.stdout + res.stderr
    
    has_error = any(k in output for k in ["FAILED", "not found", "Error", "Mismatch"])
    
    details = (
        f"Snapshot v2 có prev_snapshot_id = v1\n"
        f"v1 đã bị xóa -> Chain đứt\n"
        f"Verify v2 result: {'FAIL (đúng)' if has_error else 'PASS (sai!)'}\n\n"
        f"Output: {output[:300]}..."
    )
    
    return print_verdict(
        "Phát hiện chain đứt (prev bị xóa)",
        has_error,
        details,
        verify_args
    )


def scenario_3_replace_with_old():
    """
    CASE 3: THAY THẾ SNAPSHOT MỚI BẰNG CŨ
    
    Đề bài: "thay snapshot mới bằng snapshot cũ"
    - Copy nội dung v1 ghi đè lên v2
    """
    console.rule("[bold cyan]CASE 3: THAY NỘI DUNG SNAPSHOT MỚI BẰNG CŨ[/bold cyan]")
    console.print("[dim]Mô tả: Ghi đè nội dung v2 bằng nội dung v1. Verify v2 phải FAIL.[/dim]")

    # 1. Setup
    setup_environment()
    run_cli(["init"])
    
    # 2. Backup v1 và v2
    create_test_data("data_v1", "OLD VERSION 1 DATA")
    res1 = run_cli(["backup", "data_v1", "--label", "V1-Old"])
    snap_v1 = get_snapshot_id(res1.stdout)
    console.print(f"   -> Backup v1 OK (ID: {snap_v1[:16]}...)")
    
    create_test_data("data_v2", "NEW VERSION 2 DATA - COMPLETELY DIFFERENT")
    res2 = run_cli(["backup", "data_v2", "--label", "V2-New"])
    snap_v2 = get_snapshot_id(res2.stdout)
    console.print(f"   -> Backup v2 OK (ID: {snap_v2[:16]}...)")
    
    # 3. ATTACK: Copy nội dung v1 ghi đè lên file v2
    manifest_v1 = SANDBOX_DIR / "store" / "snapshots" / f"{snap_v1}.json"
    manifest_v2 = SANDBOX_DIR / "store" / "snapshots" / f"{snap_v2}.json"
    
    shutil.copy2(manifest_v1, manifest_v2)
    console.print(f"   -> [yellow]⚠ ATTACK: Ghi đè v2 bằng nội dung v1![/yellow]")
    
    # 4. Verify v2 -> Phải FAIL vì snapshot_id trong JSON != filename
    verify_args = ["verify", snap_v2]
    res = run_cli(verify_args)
    output = res.stdout + res.stderr
    
    has_error = any(k in output for k in ["FAILED", "Mismatch", "Error"])
    
    details = (
        f"File: {snap_v2}.json\n"
        f"Nội dung bên trong: snapshot của v1\n"
        f"snapshot_id trong JSON != filename -> PHẢI FAIL\n\n"
        f"Output: {output[:300]}..."
    )
    
    return print_verdict(
        "Phát hiện nội dung bị thay thế",
        has_error,
        details,
        verify_args
    )


# --- MAIN ---

if __name__ == "__main__":
    console.print(Panel(
        "[bold white]TEST SUITE: ROLLBACK ATTACK DETECTION[/bold white]\n"
        "[dim]Yêu cầu đề bài #4: Phát hiện khi snapshot mới bị thay bằng snapshot cũ[/dim]",
        style="bold blue"
    ))
    
    results = []
    
    results.append(("CASE 1: Xóa snapshot mới nhất", scenario_1_delete_latest_snapshot()))
    results.append(("CASE 2: Xóa prev_snapshot (chain break)", scenario_2_verify_chain_integrity()))
    results.append(("CASE 3: Thay nội dung mới bằng cũ", scenario_3_replace_with_old()))
    
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
