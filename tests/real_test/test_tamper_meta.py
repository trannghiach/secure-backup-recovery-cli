import os
import sys
import json
import shutil
import subprocess
import re
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# --- CẤU HÌNH ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # Lên 2 cấp: real_test -> tests -> LabCLI
SANDBOX_DIR = PROJECT_ROOT / "tests" / "sandbox_meta"
AUDIT_LOG_PATH = SANDBOX_DIR / "store" / "audit.log"  # Audit log riêng cho sandbox
CLI_CMD = [sys.executable, "-m", "src.sbackup.main"]

console = Console()

# --- HÀM HỖ TRỢ (CORE) ---

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

def run_cli(args, cwd=SANDBOX_DIR):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = f"{PROJECT_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    # Set audit log path vào sandbox
    env["SBACKUP_AUDIT_LOG_PATH"] = str(AUDIT_LOG_PATH)

    result = subprocess.run(
        CLI_CMD + args, cwd=cwd, capture_output=True, text=True,
        env=env, encoding='utf-8', errors='replace'
    )
    return result

def get_snapshot_id(output):
    match = re.search(r"([a-f0-9]{64})", output)
    return match.group(1) if match else None

def create_dummy_data():
    """Tạo dữ liệu mẫu đa dạng để test"""
    d = SANDBOX_DIR / "data"
    d.mkdir(parents=True, exist_ok=True)
    # File 1
    with open(d / "report.csv", "w") as f: f.write("ID,Name\n1,Alice")
    # File 2
    with open(d / "logo.png", "w") as f: f.write("FAKE IMAGE BYTES")
    return d

def extract_error_text(output):
    """Lọc thông báo lỗi từ CLI"""
    keywords = ["Mismatch", "FAILED", "sai lệch", "không khớp", "CẢNH BÁO", "Missing", "tampered", "invalid", "corrupted"]
    # Xóa ANSI code
    clean = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])').sub('', output)
    error_lines = []
    for line in clean.splitlines():
        if any(k.lower() in line.lower() for k in keywords) and not line.strip().startswith("╭"):
            error_lines.append(line.strip())
    return "\n".join(error_lines) if error_lines else "Không tìm thấy chi tiết lỗi."

def get_current_user():
    """Lấy tên user hiện tại"""
    import getpass
    return getpass.getuser()

def print_verdict(test_name, output, expect_fail=True, command_args=None, snap_id=None):
    """In kết quả kiểm thử đẹp mắt với thông tin chi tiết"""
    has_error = "INTEGRITY CHECK FAILED" in output or "Mismatch" in output or "FAIL" in output
    
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
        # Trường hợp kỳ vọng verify thành công
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

# --- CÁC KỊCH BẢN TẤN CÔNG ---

def scenario_1_tamper_merkle_root(snap_id):
    console.rule("[bold cyan]CASE 1: SỬA MERKLE ROOT (META)[/bold cyan]")
    console.print("[dim]Mô tả: Giữ nguyên nội dung file, nhưng sửa Merkle Root trong JSON thành giá trị rác.[/dim]")
    
    manifest_path = SANDBOX_DIR / "store" / "snapshots" / f"{snap_id}.json"
    
    # 1. Đọc
    with open(manifest_path, "r") as f: data = json.load(f)
    old_root = data['merkle_root']
    
    # 2. Sửa (Tamper)
    data['merkle_root'] = "a" * 64
    with open(manifest_path, "w") as f: json.dump(data, f)
    console.print(f"   -> Đã đổi Root: {old_root[:8]}... -> {data['merkle_root'][:8]}...")

    # 3. Verify
    verify_args = ["verify", snap_id]
    res = run_cli(verify_args)
    print_verdict("Phát hiện Fake Root", res.stdout + res.stderr, command_args=verify_args, snap_id=snap_id)
    
    # 4. Revert (Khôi phục để chạy test sau)
    data['merkle_root'] = old_root
    with open(manifest_path, "w") as f: json.dump(data, f)
    console.print("   -> [dim]Đã khôi phục file JSON gốc để test tiếp.[/dim]")

def scenario_2_tamper_file_path(snap_id):
    console.rule("[bold cyan]CASE 2: SỬA ĐƯỜNG DẪN FILE (META)[/bold cyan]")
    console.print("[dim]Mô tả: Sửa đường dẫn 'data/report.csv' thành 'data/HACKED.csv' trong JSON. Verify phải tính lại hash và thấy sai lệch.[/dim]")

    manifest_path = SANDBOX_DIR / "store" / "snapshots" / f"{snap_id}.json"
    
    # 1. Đọc
    with open(manifest_path, "r") as f: data = json.load(f)
    
    # 2. Sửa (Tamper)
    original_path = data['files'][0]['path']
    data['files'][0]['path'] = "data/HACKED.csv"
    
    with open(manifest_path, "w") as f: json.dump(data, f)
    console.print(f"   -> Đã đổi Path: {original_path} -> {data['files'][0]['path']}")

    # 3. Verify
    verify_args = ["verify", snap_id]
    res = run_cli(verify_args)
    print_verdict("Phát hiện đổi Path", res.stdout + res.stderr, command_args=verify_args, snap_id=snap_id)

    # 4. Revert
    data['files'][0]['path'] = original_path
    with open(manifest_path, "w") as f: json.dump(data, f)
    console.print("   -> [dim]Đã khôi phục file JSON gốc.[/dim]")

def scenario_3_tamper_chunk_list(snap_id):
    console.rule("[bold cyan]CASE 3: TRÁO ĐỔI CHUNK (META)[/bold cyan]")
    console.print("[dim]Mô tả: Tráo chunk của file này sang file kia trong JSON. Hash file sẽ thay đổi -> Merkle thay đổi.[/dim]")

    manifest_path = SANDBOX_DIR / "store" / "snapshots" / f"{snap_id}.json"
    
    # 1. Đọc
    with open(manifest_path, "r") as f: data = json.load(f)
    
    if len(data['files']) < 2:
        console.print("[yellow]Không đủ file để test tráo chunk, bỏ qua.[/yellow]")
        return

    # 2. Sửa (Tamper): Lấy chunk của file 2 gán cho file 1
    chunks_file_1 = data['files'][0]['chunks']
    chunks_file_2 = data['files'][1]['chunks']
    
    # Tráo chunk
    data['files'][0]['chunks'] = chunks_file_2
    
    with open(manifest_path, "w") as f: json.dump(data, f)
    console.print(f"   -> Đã tráo Chunk List của '{data['files'][0]['path']}' bằng chunk của file khác.")

    # 3. Verify
    verify_args = ["verify", snap_id]
    res = run_cli(verify_args)
    print_verdict("Phát hiện tráo Chunk", res.stdout + res.stderr, command_args=verify_args, snap_id=snap_id)

    # Không cần Revert vì là test cuối

# --- MAIN RUNNER ---

if __name__ == "__main__":
    console.print(Panel("[bold white]TEST SUITE: TAMPER METADATA (3 CASES)[/bold white]", style="bold blue"))
    
    # 1. Setup chung
    setup_environment()
    run_cli(["init"])
    create_dummy_data()
    
    # 2. Backup chuẩn (Baseline)
    console.print("   -> Đang tạo Backup gốc...", end=" ")
    res = run_cli(["backup", "data", "--label", "FullMetaTest"])
    if res.returncode != 0:
        console.print("[red]FAIL[/red]")
        sys.exit(1)
        
    snap_id = get_snapshot_id(res.stdout)
    console.print(f"[green]OK[/green] (ID: {snap_id})")

    # 3. Chạy từng kịch bản (Tuần tự trên cùng 1 snapshot)
    scenario_1_tamper_merkle_root(snap_id)
    scenario_2_tamper_file_path(snap_id)
    scenario_3_tamper_chunk_list(snap_id)