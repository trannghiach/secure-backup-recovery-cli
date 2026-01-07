"""
TEST SUITE: RESTORE & COMPARE
=============================
Kiểm tra khả năng restore và so sánh với source gốc.

Yêu cầu: Xoá một số file từ source, restore từ snapshot 
và so sánh kết quả (cây thư mục + nội dung file).
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
SANDBOX_DIR = PROJECT_ROOT / "tests" / "sandbox_restore"
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

def get_current_user():
    import getpass
    return getpass.getuser()

def create_test_data():
    """Tạo cấu trúc thư mục test với nhiều file."""
    data_dir = SANDBOX_DIR / "source_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    # Tạo nhiều file với nội dung khác nhau
    files = {
        "file1.txt": "Content of file 1 - Hello World",
        "file2.txt": "Content of file 2 - Important data ABC123",
        "subdir/file3.txt": "Content in subdirectory - Nested file",
        "subdir/deep/file4.txt": "Deep nested content - Level 2",
        "report.csv": "id,name,value\n1,test,100\n2,demo,200",
    }
    
    for rel_path, content in files.items():
        file_path = data_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            f.write(content)
    
    return data_dir, files

def get_dir_tree(path):
    """Lấy cây thư mục và nội dung file."""
    tree = {}
    for root, dirs, files in os.walk(path):
        for f in files:
            full = Path(root) / f
            rel = full.relative_to(path).as_posix()
            with open(full, "r", errors='replace') as fp:
                tree[rel] = fp.read()
    return tree

def compare_trees(original, restored):
    """So sánh 2 cây thư mục."""
    missing = set(original.keys()) - set(restored.keys())
    extra = set(restored.keys()) - set(original.keys())
    different = []
    
    for f in original:
        if f in restored and original[f] != restored[f]:
            different.append(f)
    
    return {
        "missing": missing,
        "extra": extra,
        "different": different,
        "match": len(missing) == 0 and len(extra) == 0 and len(different) == 0
    }

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

# --- KỊCH BẢN TEST ---

def scenario_1_restore_full():
    """
    CASE 1: RESTORE TOÀN BỘ DỮ LIỆU
    
    Backup -> Xóa source -> Restore -> So sánh phải giống hệt
    """
    console.rule("[bold cyan]CASE 1: RESTORE FULL - So sánh cây thư mục[/bold cyan]")
    
    # 1. Setup
    setup_environment()
    run_cli(["init"])
    
    # 2. Tạo dữ liệu và backup
    source_dir, original_files = create_test_data()
    original_tree = get_dir_tree(source_dir)
    
    console.print(f"   -> Tạo {len(original_files)} files trong source")
    
    res = run_cli(["backup", "source_data", "--label", "FullBackup"])
    snap_id = get_snapshot_id(res.stdout)
    
    if not snap_id:
        console.print("[red]Backup failed![/red]")
        return False
    console.print(f"   -> Backup OK (ID: {snap_id[:16]}...)")
    
    # 3. Xóa hoàn toàn source
    shutil.rmtree(source_dir)
    console.print("   -> [yellow]Đã XÓA toàn bộ source_data[/yellow]")
    
    # 4. Restore
    restore_dir = SANDBOX_DIR / "restored"
    restore_args = ["restore", snap_id, str(restore_dir)]
    res = run_cli(restore_args)
    
    # 5. So sánh
    restored_tree = get_dir_tree(restore_dir)
    comparison = compare_trees(original_tree, restored_tree)
    
    details = (
        f"Files gốc: {len(original_tree)}\n"
        f"Files restored: {len(restored_tree)}\n"
        f"Missing: {comparison['missing'] or 'None'}\n"
        f"Extra: {comparison['extra'] or 'None'}\n"
        f"Different: {comparison['different'] or 'None'}"
    )
    
    return print_verdict(
        "Restore toàn bộ - cây thư mục khớp",
        comparison['match'],
        details,
        restore_args
    )


def scenario_2_restore_after_partial_delete():
    """
    CASE 2: RESTORE SAU KHI XÓA MỘT SỐ FILE
    
    Backup -> Xóa vài file từ source -> Restore -> So sánh
    """
    console.rule("[bold cyan]CASE 2: XÓA VÀI FILE -> RESTORE[/bold cyan]")
    
    # 1. Setup
    setup_environment()
    run_cli(["init"])
    
    # 2. Tạo dữ liệu và backup
    source_dir, original_files = create_test_data()
    original_tree = get_dir_tree(source_dir)
    
    res = run_cli(["backup", "source_data", "--label", "BeforeDelete"])
    snap_id = get_snapshot_id(res.stdout)
    
    if not snap_id:
        return False
    console.print(f"   -> Backup OK (ID: {snap_id[:16]}...)")
    
    # 3. Xóa một số file (giả lập mất dữ liệu)
    files_to_delete = ["file1.txt", "subdir/file3.txt"]
    for f in files_to_delete:
        file_path = source_dir / f
        if file_path.exists():
            file_path.unlink()
    console.print(f"   -> [yellow]Đã xóa: {files_to_delete}[/yellow]")
    
    # 4. Restore vào thư mục mới
    restore_dir = SANDBOX_DIR / "restored_partial"
    restore_args = ["restore", snap_id, str(restore_dir)]
    res = run_cli(restore_args)
    
    # 5. So sánh với original (trước khi xóa)
    restored_tree = get_dir_tree(restore_dir)
    comparison = compare_trees(original_tree, restored_tree)
    
    details = (
        f"Files đã xóa từ source: {files_to_delete}\n"
        f"Restore có đủ: {comparison['match']}\n"
        f"Missing: {comparison['missing'] or 'None'}"
    )
    
    return print_verdict(
        "Restore khôi phục đủ file đã bị xóa",
        comparison['match'],
        details,
        restore_args
    )


def scenario_3_content_integrity():
    """
    CASE 3: KIỂM TRA NỘI DUNG FILE CHÍNH XÁC
    
    So sánh nội dung từng file sau restore
    """
    console.rule("[bold cyan]CASE 3: KIỂM TRA NỘI DUNG FILE[/bold cyan]")
    
    # 1. Setup
    setup_environment()
    run_cli(["init"])
    
    # 2. Tạo file với nội dung đặc biệt
    source_dir = SANDBOX_DIR / "source_content"
    source_dir.mkdir(parents=True, exist_ok=True)
    
    test_content = "Special content: ABC123!@#$%^&*() with unicode: 日本語 한국어"
    with open(source_dir / "special.txt", "w", encoding="utf-8") as f:
        f.write(test_content)
    
    # 3. Backup
    res = run_cli(["backup", "source_content", "--label", "ContentTest"])
    snap_id = get_snapshot_id(res.stdout)
    
    if not snap_id:
        return False
    console.print(f"   -> Backup OK")
    
    # 4. Xóa source và restore
    shutil.rmtree(source_dir)
    restore_dir = SANDBOX_DIR / "restored_content"
    restore_args = ["restore", snap_id, str(restore_dir)]
    run_cli(restore_args)
    
    # 5. So sánh nội dung
    restored_file = restore_dir / "special.txt"
    if not restored_file.exists():
        return print_verdict("Kiểm tra nội dung", False, "File không tồn tại sau restore", restore_args)
    
    with open(restored_file, "r", encoding="utf-8") as f:
        restored_content = f.read()
    
    content_match = restored_content == test_content
    details = (
        f"Original: {test_content[:50]}...\n"
        f"Restored: {restored_content[:50]}...\n"
        f"Match: {content_match}"
    )
    
    return print_verdict(
        "Nội dung file khớp chính xác",
        content_match,
        details,
        restore_args
    )


# --- MAIN ---

if __name__ == "__main__":
    console.print(Panel(
        "[bold white]TEST SUITE: RESTORE & COMPARE[/bold white]\n"
        "[dim]Xóa file source -> Restore -> So sánh[/dim]",
        style="bold blue"
    ))
    
    results = []
    
    results.append(("CASE 1: Restore full", scenario_1_restore_full()))
    results.append(("CASE 2: Xóa vài file -> Restore", scenario_2_restore_after_partial_delete()))
    results.append(("CASE 3: Nội dung file", scenario_3_content_integrity()))
    
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
