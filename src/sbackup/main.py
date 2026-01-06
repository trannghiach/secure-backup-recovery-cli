# src/sbackup/main.py
import typer
import time
import os
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# --- MOCKING ---
from .mocks import MockStorage as Storage
from .mocks import MockLogic as Logic
from .mocks import MockSecurity as Security

app = typer.Typer(help="Secure Backup CLI")
console = Console()

storage = Storage()
logic = Logic()
security = Security()

def enforce_security(command: str, args_str: str):
    user = security.get_current_user()
    if not security.check_permission(user, command):
        console.print(f"[bold red]⛔ ACCESS DENIED:[/bold red] User '{user}'")
        security.log_audit(user, command, args_str, "DENY")
        raise typer.Exit(code=1)
    return user

@app.command()
def init(store_path: str = typer.Argument("store", help="Đường dẫn đến store")):
    """Khởi tạo backup store."""
    user = enforce_security("init", store_path)
    
    # Vì Interface IStorage của bạn chưa có hàm init_store
    # Dev 1 xử lý tạm bằng lệnh os.makedirs ngay tại đây
    try:
        os.makedirs(os.path.join(store_path, "chunks"), exist_ok=True)
        os.makedirs(os.path.join(store_path, "snapshots"), exist_ok=True)
        console.print(f"[green]✔ Store khởi tạo thành công tại: {store_path}[/green]")
        security.log_audit(user, "init", store_path, "OK")
    except Exception as e:
        console.print(f"[red]Lỗi: {e}[/red]")
        security.log_audit(user, "init", store_path, "FAIL")

@app.command()
def backup(source: str, label: str = typer.Option(..., "--label", help="Nhãn")):
    """Sao lưu thư mục."""
    user = enforce_security("backup", f"{source} {label}")
    console.print(Panel(f"Job: Backup [yellow]{source}[/yellow]", title="Processing"))

    try:
        # 1. Chunking
        with console.status("[green]Đang cắt chunk...[/green]"):
            time.sleep(1)
            # Interface trả về list hash string (List[str])
            chunk_hashes = logic.chunk_data(source)
            console.print(f"✔ Đã xác định {len(chunk_hashes)} chunks.")

        # 2. Lưu chunk
        with console.status("[blue]Đang lưu xuống đĩa...[/blue]"):
            time.sleep(0.5)
            for ch_hash in chunk_hashes:
                # Gọi save_chunk với hash string
                storage.save_chunk(ch_hash, b"dummy_data")
        
        # 3. Manifest
        manifest = logic.create_manifest(label, source)
        if storage.save_manifest(manifest):
            # Vì save_manifest trả về bool, ta tự hiện thông báo thành công
            console.print(f"[bold green]✔ BACKUP SUCCESS![/bold green] Snapshot ID: {manifest.snapshot_id}")
            security.log_audit(user, "backup", f"{source} {label}", "OK")
        else:
            console.print("[red]Lỗi khi lưu Manifest[/red]")
            security.log_audit(user, "backup", f"{source} {label}", "FAIL")

    except Exception as e:
        console.print(f"[red]Lỗi: {e}[/red]")
        security.log_audit(user, "backup", f"{source} {label}", "FAIL")

@app.command(name="list-snapshots")
def list_snapshots():
    """Liệt kê snapshot."""
    user = enforce_security("list-snapshots", "")
    snapshots = storage.list_snapshots()
    
    table = Table(title="Danh sách Snapshot")
    table.add_column("ID", style="cyan")
    
    for snap in snapshots:
        table.add_row(snap)
        
    console.print(table)
    security.log_audit(user, "list-snapshots", "", "OK")

@app.command()
def verify(snapshot_id: str):
    """Verify snapshot."""
    user = enforce_security("verify", snapshot_id)
    
    # Load manifest
    manifest = storage.load_manifest(snapshot_id)
    # Gọi verify_merkle (đúng tên trong interface của bạn)
    is_valid = logic.verify_merkle(manifest)

    if is_valid:
        console.print("[green]✔ VERIFY OK[/green]")
        security.log_audit(user, "verify", snapshot_id, "OK")
    else:
        console.print("[red]✘ VERIFY FAIL[/red]")
        security.log_audit(user, "verify", snapshot_id, "FAIL")
        
@app.command(name="audit-verify")
def audit_verify():
    """Verify the integrity of the audit log."""
    user = enforce_security("audit-verify", "")
    
    # In Mock phase, we just pretend it's OK
    # Later, Dev 4 will implement security.verify_audit_log()
    is_valid = security.verify_audit_log()

    if is_valid:
        console.print("[green]✔ AUDIT LOG INTEGRITY: OK[/green]")
        # We don't log audit-verify into audit log itself to avoid infinite recursion loops 
        # (or depending on requirements, but usually verify ops are read-only)
    else:
        console.print("[bold red]✘ AUDIT LOG CORRUPTED![/bold red]")

if __name__ == "__main__":
    app()