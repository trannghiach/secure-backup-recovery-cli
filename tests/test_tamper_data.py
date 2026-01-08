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
SANDBOX_DIR = PROJECT_ROOT / "tests" / "sandbox_tamper"
AUDIT_LOG_PATH = SANDBOX_DIR / "store" / "audit.log"  # Audit log riêng cho sandbox
CLI_CMD = [sys.executable, "-m", "src.sbackup.main"]

console = Console()

# --- HÀM HỖ TRỢ ---

def setup_environment():
    if SANDBOX_DIR.exists():
        try: shutil.rmtree(SANDBOX_DIR)
        except: pass
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    # Copy policy.yaml vào sandbox
    policy_src = PROJECT_ROOT / "policy.yaml"
    policy_dst = SANDBOX_DIR / "policy.yaml"
    if policy_src.exists():
        shutil.copy2(policy_src, policy_dst)
    console.print(f"[dim]Initialized Sandbox at: {SANDBOX_DIR}[/dim]")

def run_cli(args, cwd=SANDBOX_DIR):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = f"{PROJECT_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    # Set audit log path vào sandbox
    env["SBACKUP_AUDIT_LOG_PATH"] = str(AUDIT_LOG_PATH)

    result = subprocess.run(
        CLI_CMD + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        encoding='utf-8',
        errors='replace'
    )
    return result

def get_snapshot_id(output):
    match = re.search(r"([a-f0-9]{64})", output)
    return match.group(1) if match else None

def create_file(name, content):
    p = SANDBOX_DIR / name
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p

# --- HÀM HỖ TRỢ THÊM ---
def get_current_user():
    """Lấy tên user hiện tại"""
    import getpass
    return getpass.getuser()

# --- [FIX] HÀM TRÍCH XUẤT LỖI THÔNG MINH ---
def extract_error_text(output):
    """
    Lọc bỏ mã màu ANSI và đường viền bảng của Rich.
    Tìm dòng chứa từ khóa lỗi quan trọng.
    """
    # 1. Xóa mã màu ANSI
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    clean_text = ansi_escape.sub('', output)
    
    lines = clean_text.splitlines()
    error_lines = []
    
    # 2. Tìm các dòng chứa keyword lỗi
    keywords = ["CẢNH BÁO", "Mismatch", "FAILED", "Missing", "Lỗi", "không khớp", "tampered", "invalid", "corrupted"]
    
    for line in lines:
        line = line.strip()
        # Bỏ qua dòng vẽ bảng (chứa ký tự đặc biệt ở đầu)
        if line.startswith("╭") or line.startswith("╰") or line.startswith("│"):
            # Trừ khi dòng vẽ bảng đó chứa chữ bên trong
            clean_content = line.strip("╭╰│─ ")
            if any(k.lower() in clean_content.lower() for k in keywords):
                error_lines.append(clean_content)
        # Lấy dòng text thường
        elif any(k.lower() in line.lower() for k in keywords):
            error_lines.append(line)
            
    if error_lines:
        return "\n".join(error_lines)
    return "Không tìm thấy nội dung text lỗi (Check raw output)"

def print_verdict(test_name, output, expect_fail=True, command_args=None, snap_id=None):
    """In kết quả kiểm thử đẹp mắt với thông tin chi tiết"""
    has_error = "INTEGRITY CHECK FAILED" in output or "Mismatch" in output or "FAIL" in output or "Missing" in output or "Error" in output
    
    # Thông tin command đã chạy
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
        else:
            console.print(Panel(
                f"[bold red]✘ FAIL: {test_name}[/bold red]\n\n"
                f"[cyan]📋 Command đã chạy:[/cyan] [white]{cmd_str}[/white]\n"
                f"[cyan]👤 User thực thi:[/cyan] [white]{user}[/white]\n"
                f"[cyan]🔑 Snapshot ID:[/cyan] [white]{snap_id if snap_id else 'N/A'}[/white]\n\n"
                "[bold red]⚠️ Hệ thống KHÔNG phát hiện sự thay đổi![/bold red]\n\n"
                f"[dim]📊 Output nhận được:[/dim]\n[dim]{output[:500]}{'...' if len(output) > 500 else ''}[/dim]",
                border_style="red",
                title="[bold]KẾT QUẢ KIỂM THỬ[/bold]"
            ))
    else:
        if not has_error:
            console.print(Panel(
                f"[bold green]✔ PASS: {test_name}[/bold green]\n\n"
                f"[cyan]📋 Command đã chạy:[/cyan] [white]{cmd_str}[/white]\n"
                f"[cyan]👤 User thực thi:[/cyan] [white]{user}[/white]",
                border_style="green"
            ))
        else:
            console.print(Panel(
                f"[bold red]✘ FAIL: {test_name}[/bold red]\n\n"
                f"[cyan]📋 Command đã chạy:[/cyan] [white]{cmd_str}[/white]\n"
                f"[cyan]👤 User thực thi:[/cyan] [white]{user}[/white]",
                border_style="red"
            ))

# --- CÁC TEST CASE ---

def scenario_1_bit_flip():
    console.print("\n[bold cyan]KỊCH BẢN 1: BIT FLIP ATTACK (Sửa nội dung Chunk)[/bold cyan]")

    # 1. Setup & Backup
    create_file("data/secret_1.txt", "Launch code: 123456")
    res = run_cli(["backup", "data", "--label", "FlipTest"])
    if res.returncode != 0: return console.print("[red]Backup Fail[/red]")
    
    snap_id = get_snapshot_id(res.stdout)
    console.print(f"   -> Backup OK (ID: {snap_id[:8]}...)")

    # 2. Tamper
    manifest_path = SANDBOX_DIR / "store" / "snapshots" / f"{snap_id}.json"
    with open(manifest_path) as f: manifest = json.load(f)
    chunk_hash = manifest['files'][0]['chunks'][0]
    chunk_path = SANDBOX_DIR / "store" / "chunks" / chunk_hash
    
    console.print(f"   -> Tấn công chunk: [yellow]{chunk_hash[:8]}...[/yellow]")
    with open(chunk_path, "r+b") as f:
        f.seek(0); byte = f.read(1); f.seek(0)
        f.write(bytes([byte[0] ^ 0xFF]))
    console.print("      [red]⚠ Đã tiêm mã độc (Bit Flip)[/red]")

    # 3. Verify
    console.print("   -> Chạy Verify...")
    verify_args = ["verify", snap_id]
    res = run_cli(verify_args)
    output = res.stdout + res.stderr
    
    # 4. Assert & Extract Message
    print_verdict("BIT FLIP ATTACK - Phát hiện chunk bị sửa đổi", output, command_args=verify_args, snap_id=snap_id)

def scenario_2_deletion():
    console.print("\n[bold cyan]KỊCH BẢN 2: DELETION ATTACK (Xóa file Chunk)[/bold cyan]")

    # 1. Setup
    setup_environment(); run_cli(["init"])
    create_file("data/img.png", "FakeData")
    res = run_cli(["backup", "data", "--label", "DelTest"])
    snap_id = get_snapshot_id(res.stdout)
    console.print(f"   -> Backup OK (ID: {snap_id[:8]}...)")

    # 2. Tamper
    manifest_path = SANDBOX_DIR / "store" / "snapshots" / f"{snap_id}.json"
    with open(manifest_path) as f: manifest = json.load(f)
    chunk_hash = manifest['files'][0]['chunks'][0]
    os.remove(SANDBOX_DIR / "store" / "chunks" / chunk_hash)
    console.print(f"   -> Đã xóa chunk: [yellow]{chunk_hash[:8]}...[/yellow]")

    # 3. Verify
    console.print("   -> Chạy Verify...")
    verify_args = ["verify", snap_id]
    res = run_cli(verify_args)
    output = res.stdout + res.stderr

    # 4. Assert
    print_verdict("DELETION ATTACK - Phát hiện chunk bị xóa", output, command_args=verify_args, snap_id=snap_id)

if __name__ == "__main__":
    console.print(Panel("[bold white]TEST SUITE: TAMPER DATA[/bold white]", style="bold blue"))
    setup_environment()
    run_cli(["init"])
    scenario_1_bit_flip()
    scenario_2_deletion()