import os
import sys
import shutil
import subprocess
import re
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

# --- CẤU HÌNH ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # Lên 2 cấp: real_test -> tests -> LabCLI
SANDBOX_DIR = PROJECT_ROOT / "tests" / "sandbox_audit"
# Audit log sẽ được ghi vào sandbox khi test (qua env var)
AUDIT_LOG_PATH = SANDBOX_DIR / "store" / "audit.log"
CLI_CMD = [sys.executable, "-m", "src.sbackup.main"]

console = Console()

# --- HÀM HỖ TRỢ ---

def setup_environment():
    if SANDBOX_DIR.exists():
        try: shutil.rmtree(SANDBOX_DIR)
        except: pass
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    # Đảm bảo thư mục store tồn tại cho audit log
    (SANDBOX_DIR / "store").mkdir(parents=True, exist_ok=True)
    # Copy policy.yaml vào sandbox
    policy_src = PROJECT_ROOT / "policy.yaml"
    policy_dst = SANDBOX_DIR / "policy.yaml"
    if policy_src.exists():
        shutil.copy2(policy_src, policy_dst)

def run_cli(args, cwd=SANDBOX_DIR):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = f"{PROJECT_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    # Set audit log path vào sandbox để không ảnh hưởng chương trình chính
    env["SBACKUP_AUDIT_LOG_PATH"] = str(AUDIT_LOG_PATH)

    result = subprocess.run(
        CLI_CMD + args, cwd=cwd, capture_output=True, text=True,
        env=env, encoding='utf-8', errors='replace'
    )
    return result

def create_traffic():
    """Tạo ra một lượng log nhất định để test"""
    run_cli(["init"])
    # Tạo folder data giả để backup
    d = SANDBOX_DIR / "logs_data"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "file.txt", "w") as f: f.write("data")
    
    # Chạy vài lệnh để sinh log
    run_cli(["backup", "logs_data", "--label", "LogTest1"])
    run_cli(["list-snapshots"])
    run_cli(["backup", "logs_data", "--label", "LogTest2"])
    run_cli(["list-snapshots"])  # Thêm lệnh nữa để đủ log
    
    # Kiểm tra xem log đã được tạo chưa
    if AUDIT_LOG_PATH.exists():
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
            line_count = len(f.readlines())
        console.print(f"[dim]   -> Đã tạo traffic log mẫu ({line_count} dòng).[/dim]")
    else:
        console.print(f"[yellow]   -> CẢNH BÁO: Audit log không được tạo![/yellow]")

def get_current_user():
    """Lấy tên user hiện tại"""
    import getpass
    return getpass.getuser()

def extract_error_text(output):
    """Lọc thông báo lỗi từ CLI"""
    keywords = ["CORRUPTED", "Modified", "Broken", "modified", "chain", "Malformed", "tampered", "invalid", "mismatch", "FAILED"]
    clean = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])').sub('', output)
    error_lines = []
    for line in clean.splitlines():
        if any(k.lower() in line.lower() for k in keywords) and not line.strip().startswith("╭"):
            # Loại bỏ các ký tự viền bảng Rich
            cleaned_line = line.strip().strip("│┌┐└┘─ ")
            if cleaned_line:
                error_lines.append(cleaned_line)
    return "\n".join(error_lines) if error_lines else "Không tìm thấy chi tiết lỗi."

def print_verdict(test_name, output, command_args=None):
    """In kết quả kiểm thử đẹp mắt với thông tin chi tiết"""
    has_error = "CORRUPTED" in output or "FAIL" in output or "Modified" in output or "Broken" in output
    
    # Thông tin command đã chạy
    user = get_current_user()
    cmd_str = f"sbackup {' '.join(command_args)}" if command_args else "N/A"
    
    if has_error:
        msg = extract_error_text(output)
        console.print(Panel(
            f"[bold green]✔ PASS: {test_name}[/bold green]\n\n"
            f"[cyan]📋 Command đã chạy:[/cyan] [white]{cmd_str}[/white]\n"
            f"[cyan]👤 User thực thi:[/cyan] [white]{user}[/white]\n\n"
            f"[bold yellow]🔍 Hệ thống đã phát hiện:[/bold yellow]\n[yellow]{msg}[/yellow]\n\n"
            f"[dim]📊 Chi tiết output:[/dim]\n[dim]{output[:500]}{'...' if len(output) > 500 else ''}[/dim]",
            border_style="green",
            title="[bold]KẾT QUẢ KIỂM THỬ[/bold]"
        ))
    else:
        console.print(Panel(
            f"[bold red]✘ FAIL: {test_name}[/bold red]\n\n"
            f"[cyan]📋 Command đã chạy:[/cyan] [white]{cmd_str}[/white]\n"
            f"[cyan]👤 User thực thi:[/cyan] [white]{user}[/white]\n\n"
            "[bold red]⚠️ Hệ thống KHÔNG phát hiện log bị sửa![/bold red]\n\n"
            f"[dim]📊 Output nhận được:[/dim]\n[dim]{output[:500]}{'...' if len(output) > 500 else ''}[/dim]",
            border_style="red",
            title="[bold]KẾT QUẢ KIỂM THỬ[/bold]"
        ))

# --- KỊCH BẢN TẤN CÔNG ---

def scenario_1_modify_content():
    console.rule("[bold cyan]CASE 1: SỬA NỘI DUNG LOG (Data Integrity)[/bold cyan]")
    console.print("[dim]Mô tả: Hacker sửa trạng thái lệnh trong log từ 'OK' thành 'FAKE'. Hash dòng đó sẽ không khớp nội dung.[/dim]")

    # 1. Reset & Setup
    setup_environment()
    create_traffic()
    
    log_path = AUDIT_LOG_PATH
    
    # Kiểm tra file tồn tại
    if not log_path.exists():
        return console.print(f"[red]Log file không tồn tại: {log_path}[/red]")
    
    # 2. Tamper: Sửa dòng cuối cùng
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    if not lines: return console.print("[red]Log file empty![/red]")

    # Giả sử dòng cuối là OK, ta sửa thành FAKE_STATUS
    # Format: HASH PREV_HASH TS USER CMD ARGS STATUS
    # Ta replace chuỗi "OK" ở cuối thành "FAKE"
    original_line = lines[-1]
    tampered_line = original_line.replace("OK", "FAKE")
    
    # Nếu dòng đó không có OK (ví dụ lệnh fail), ta thêm text vào để làm sai hash
    if tampered_line == original_line:
        tampered_line = original_line.strip() + "_HACKED\n"

    lines[-1] = tampered_line
    
    with open(log_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
        
    console.print(f"   -> Đã sửa dòng cuối audit.log")

    # 3. Verify
    console.print("   -> Chạy Audit Verify...")
    verify_args = ["audit-verify"]
    res = run_cli(verify_args)
    print_verdict("Phát hiện sửa nội dung", res.stdout + res.stderr, command_args=verify_args)


def scenario_2_break_chain():
    console.rule("[bold cyan]CASE 2: XÓA DÒNG LOG (Chain Integrity)[/bold cyan]")
    console.print("[dim]Mô tả: Hacker xóa một dòng ở giữa. PrevHash của dòng sau sẽ không khớp với EntryHash dòng trước.[/dim]")

    # 1. Reset & Setup
    setup_environment()
    create_traffic() # Tạo khoảng 4-5 dòng log
    
    log_path = AUDIT_LOG_PATH
    
    # Kiểm tra file tồn tại
    if not log_path.exists():
        return console.print(f"[red]Log file không tồn tại: {log_path}[/red]")
    
    # 2. Tamper: Xóa dòng thứ 2 (index 1)
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    if len(lines) < 3: return console.print("[red]Không đủ log để test chain break![/red]")

    deleted_line = lines.pop(1) # Xóa dòng giữa
    
    with open(log_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
        
    console.print(f"   -> Đã xóa dòng log thứ 2.")

    # 3. Verify
    console.print("   -> Chạy Audit Verify...")
    verify_args = ["audit-verify"]
    res = run_cli(verify_args)
    print_verdict("Phát hiện đứt gãy Hash Chain", res.stdout + res.stderr, command_args=verify_args)

# --- MAIN ---

if __name__ == "__main__":
    console.print(Panel("[bold white]TEST SUITE: AUDIT LOG INTEGRITY[/bold white]", style="bold blue"))
    scenario_1_modify_content()
    scenario_2_break_chain()