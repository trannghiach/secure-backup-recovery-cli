"""
TEST SUITE: POLICY ACCESS CONTROL
=================================
Kiểm tra hệ thống phân quyền và audit log DENY.

Yêu cầu: Chạy một lệnh không được phép dựa theo role của OS user 
hiện tại và phải bị từ chối và có audit log DENY.
"""

import os
import sys
import shutil
import subprocess
import re
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

# --- CẤU HÌNH ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SANDBOX_DIR = PROJECT_ROOT / "tests" / "sandbox_policy"
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

def run_cli(args, cwd=SANDBOX_DIR, policy_path=None):
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

def get_current_user():
    """Lấy username theo format của SecurityManager."""
    import platform
    import getpass
    
    system = platform.system()
    if system == 'Windows':
        username = getpass.getuser()
        domain = os.environ.get('USERDOMAIN', 'ANONYMOUS')
        return f"{domain}\\{username}"
    else:
        return getpass.getuser()

def read_audit_log():
    """Đọc nội dung audit log."""
    if not AUDIT_LOG_PATH.exists():
        return []
    with open(AUDIT_LOG_PATH, "r") as f:
        return f.readlines()

def find_deny_in_audit(command_pattern):
    """Tìm entry DENY trong audit log."""
    lines = read_audit_log()
    for line in lines:
        if "DENY" in line and command_pattern in line:
            return line.strip()
    return None

def print_verdict(test_name, success, details="", command_args=None):
    """In kết quả kiểm thử."""
    user = get_current_user()
    cmd_str = f"sbackup {' '.join(command_args)}" if command_args else "N/A"
    
    if success:
        console.print(Panel(
            f"[bold green]PASS: {test_name}[/bold green]\n\n"
            f"[cyan]Command:[/cyan] {cmd_str}\n"
            f"[cyan]User:[/cyan] {user}\n\n"
            f"{details}",
            border_style="green"
        ))
        return True
    else:
        console.print(Panel(
            f"[bold red]FAIL: {test_name}[/bold red]\n\n"
            f"[cyan]Command:[/cyan] {cmd_str}\n"
            f"[cyan]User:[/cyan] {user}\n\n"
            f"[red]{details}[/red]",
            border_style="red"
        ))
        return False

def create_restricted_policy():
    """Tạo policy file với user hiện tại bị hạn chế quyền."""
    user = get_current_user()
    
    # Policy: user hiện tại chỉ có role "auditor" -> không có quyền backup, init
    policy_content = f"""users:
  # Current user has auditor role (read-only)
  {user}: auditor
  # Fake admin user for testing
  fake_admin: admin

roles:
  admin: [init, backup, list-snapshots, verify, restore, audit-verify]
  operator: [backup, list-snapshots, verify, restore, audit-verify]
  auditor: [list-snapshots, verify, audit-verify]
"""
    policy_path = SANDBOX_DIR / "policy.yaml"
    with open(policy_path, "w", encoding="utf-8") as f:
        f.write(policy_content)
    
    return policy_path

# --- KỊCH BẢN TEST ---

def scenario_1_deny_init():
    """
    CASE 1: AUDITOR KHÔNG ĐƯỢC PHÉP INIT
    
    User với role auditor chạy init -> phải bị DENY
    """
    console.rule("[bold cyan]CASE 1: AUDITOR CHẠY INIT -> DENY[/bold cyan]")
    
    # 1. Setup với policy hạn chế
    setup_environment()
    create_restricted_policy()
    
    user = get_current_user()
    console.print(f"   -> User: {user} (role: auditor)")
    
    # 2. Chạy init (không được phép với auditor)
    init_args = ["init"]
    res = run_cli(init_args)
    output = res.stdout + res.stderr
    
    # 3. Kiểm tra bị từ chối
    access_denied = "ACCESS DENIED" in output or "DENY" in output or res.returncode != 0
    
    # 4. Kiểm tra audit log có DENY
    deny_entry = find_deny_in_audit("init")
    has_audit_deny = deny_entry is not None
    
    success = access_denied and has_audit_deny
    details = (
        f"Access Denied: {access_denied}\n"
        f"Audit DENY entry: {deny_entry or 'NOT FOUND'}\n"
        f"Output: {output[:200]}..."
    )
    
    return print_verdict(
        "Auditor bi tu choi khi chay init",
        success,
        details,
        init_args
    )


def scenario_2_deny_backup():
    """
    CASE 2: AUDITOR KHÔNG ĐƯỢC PHÉP BACKUP
    
    User với role auditor chạy backup -> phải bị DENY
    """
    console.rule("[bold cyan]CASE 2: AUDITOR CHẠY BACKUP -> DENY[/bold cyan]")
    
    # 1. Setup
    setup_environment()
    create_restricted_policy()
    
    # Tạo thư mục data để backup (dù sẽ bị deny)
    (SANDBOX_DIR / "data").mkdir(exist_ok=True)
    (SANDBOX_DIR / "data" / "test.txt").write_text("test")
    
    user = get_current_user()
    console.print(f"   -> User: {user} (role: auditor)")
    
    # 2. Chạy backup (không được phép với auditor)
    backup_args = ["backup", "data", "--label", "test"]
    res = run_cli(backup_args)
    output = res.stdout + res.stderr
    
    # 3. Kiểm tra
    access_denied = "ACCESS DENIED" in output or "DENY" in output or res.returncode != 0
    deny_entry = find_deny_in_audit("backup")
    has_audit_deny = deny_entry is not None
    
    success = access_denied and has_audit_deny
    details = (
        f"Access Denied: {access_denied}\n"
        f"Audit DENY entry: {deny_entry or 'NOT FOUND'}\n"
        f"Output: {output[:200]}..."
    )
    
    return print_verdict(
        "Auditor bi tu choi khi chay backup",
        success,
        details,
        backup_args
    )


def scenario_3_allow_verify():
    """
    CASE 3: AUDITOR ĐƯỢC PHÉP VERIFY
    
    Kiểm tra ngược - auditor CÓ quyền verify
    """
    console.rule("[bold cyan]CASE 3: AUDITOR CHẠY VERIFY -> ALLOW[/bold cyan]")
    
    # 1. Setup với policy đầy đủ (admin) trước để tạo snapshot
    setup_environment()
    
    # Tạm thời dùng policy cho phép init
    policy_src = PROJECT_ROOT / "policy.yaml"
    policy_dst = SANDBOX_DIR / "policy.yaml"
    if policy_src.exists():
        shutil.copy2(policy_src, policy_dst)
    
    run_cli(["init"])
    
    # Tạo data và backup
    (SANDBOX_DIR / "data").mkdir(exist_ok=True)
    (SANDBOX_DIR / "data" / "test.txt").write_text("test content")
    
    res = run_cli(["backup", "data", "--label", "test"])
    match = re.search(r"([a-f0-9]{64})", res.stdout)
    snap_id = match.group(1) if match else "fake_id"
    
    # 2. Chuyển sang policy hạn chế
    create_restricted_policy()
    
    user = get_current_user()
    console.print(f"   -> User: {user} (role: auditor)")
    
    # 3. Chạy verify (được phép với auditor)
    verify_args = ["verify", snap_id]
    res = run_cli(verify_args)
    output = res.stdout + res.stderr
    
    # 4. Kiểm tra KHÔNG bị deny
    access_denied = "ACCESS DENIED" in output or "DENY" in output
    
    success = not access_denied
    details = (
        f"Access Denied: {access_denied} (should be False)\n"
        f"Output: {output[:200]}..."
    )
    
    return print_verdict(
        "Auditor DUOC PHEP chay verify",
        success,
        details,
        verify_args
    )


def scenario_4_deny_restore():
    """
    CASE 4: AUDITOR KHÔNG ĐƯỢC PHÉP RESTORE
    
    User với role auditor chạy restore -> phải bị DENY
    """
    console.rule("[bold cyan]CASE 4: AUDITOR CHẠY RESTORE -> DENY[/bold cyan]")
    
    # 1. Setup
    setup_environment()
    create_restricted_policy()
    
    user = get_current_user()
    console.print(f"   -> User: {user} (role: auditor)")
    
    # 2. Chạy restore với snapshot giả (sẽ bị deny trước khi check snapshot)
    restore_args = ["restore", "fake_snapshot_id", "target_dir"]
    res = run_cli(restore_args)
    output = res.stdout + res.stderr
    
    # 3. Kiểm tra
    access_denied = "ACCESS DENIED" in output or "DENY" in output or res.returncode != 0
    deny_entry = find_deny_in_audit("restore")
    has_audit_deny = deny_entry is not None
    
    success = access_denied and has_audit_deny
    details = (
        f"Access Denied: {access_denied}\n"
        f"Audit DENY entry: {deny_entry or 'NOT FOUND'}\n"
        f"Output: {output[:200]}..."
    )
    
    return print_verdict(
        "Auditor bi tu choi khi chay restore",
        success,
        details,
        restore_args
    )


# --- MAIN ---

if __name__ == "__main__":
    console.print(Panel(
        "[bold white]TEST SUITE: POLICY ACCESS CONTROL[/bold white]\n"
        "[dim]Kiem tra phan quyen va audit log DENY[/dim]",
        style="bold blue"
    ))
    
    results = []
    
    results.append(("CASE 1: Deny init", scenario_1_deny_init()))
    results.append(("CASE 2: Deny backup", scenario_2_deny_backup()))
    results.append(("CASE 3: Allow verify", scenario_3_allow_verify()))
    results.append(("CASE 4: Deny restore", scenario_4_deny_restore()))
    
    # Summary
    console.print("\n")
    console.rule("[bold]TONG KET[/bold]")
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "[green]PASS[/green]" if result else "[red]FAIL[/red]"
        console.print(f"   {status} {name}")
    
    console.print(f"\nKet qua: {passed}/{total} test passed")
    
    if passed == total:
        console.print("[bold green]ALL TESTS PASSED![/bold green]")
    else:
        console.print("[bold red]SOME TESTS FAILED![/bold red]")
        sys.exit(1)
