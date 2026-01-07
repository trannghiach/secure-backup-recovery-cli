import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..core.storage import StorageManager
from ..security.manager import SecurityManager

console = Console()

# Khởi tạo các thành phần
storage = StorageManager("store")
security = SecurityManager()


def enforce_security(command: str) -> str:
    """Kiểm tra quyền và trả về user."""
    user = security.get_current_user()
    result = security.check_permission(user, command)
    
    if not result.success:
        console.print(Panel(f"[bold red]⛔ ACCESS DENIED[/bold red]\n{result.message}", title="Security Alert"))
        security.log_audit(user, command, "DENY")
        raise typer.Exit(code=1)
    
    return user


def init_cmd(store_path: str = typer.Argument("store", help="Tên thư mục lưu trữ")):
    """Khởi tạo kho backup (Init Store)."""
    user = enforce_security("init " + store_path)
    command = f"init {store_path}"
    
    try:
        if store_path != "store":
            storage.base_path = storage.base_path.parent / store_path
            
        storage.init()
        console.print(f"[green]✔ Khởi tạo thành công tại:[/green] [yellow]{storage.base_path}[/yellow]")
        security.log_audit(user, command, "OK")
        
    except Exception as e:
        console.print(f"[red]✘ Lỗi hệ thống: {e}[/red]")
        security.log_audit(user, command, "FAIL")


def list_snapshots_cmd():
    """Liệt kê danh sách bản sao lưu."""
    command = "list-snapshots"
    user = enforce_security(command)
    
    try:
        snapshots = storage.list_snapshots()
        
        table = Table(title=f"Danh sách Snapshot (Store: {storage.base_path.name})")
        table.add_column("STT", justify="right", style="cyan", no_wrap=True)
        table.add_column("Snapshot ID", style="magenta")
        table.add_column("Trạng thái", style="green")

        if not snapshots:
            console.print("[yellow]Chưa có bản backup nào.[/yellow]")
        else:
            for idx, snap in enumerate(snapshots, 1):
                table.add_row(str(idx), snap, "Available")
            console.print(table)
            
        security.log_audit(user, command, "OK")
        
    except Exception as e:
        console.print(f"[red]Lỗi: {e}[/red]")
        security.log_audit(user, command, "FAIL")
