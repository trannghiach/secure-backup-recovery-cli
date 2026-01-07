import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from pathlib import Path

from ..security.manager import SecurityManager
from ..core.wal import WALManager

console = Console()

# Khởi tạo Security
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


def print_banner(title: str):
    console.print(f"\n[bold cyan]➤ {title}[/bold cyan]")


def audit_verify_cmd():
    """Kiểm tra tính toàn vẹn Audit Log (Chống sửa xóa log)."""
    command = "audit-verify"
    user = enforce_security(command)
    print_banner("Audit Log Verification")

    with console.status("[bold yellow]Đang quét toàn bộ chuỗi Hash Chain...[/bold yellow]"):
        result = security.verify_audit_log()

    if result.success:
        console.print(Panel(f"[bold green]✔ {result.message}[/bold green]", title="Audit Integrity"))
        security.log_audit(user, command, "OK")
    else:
        console.print(Panel(f"[bold red]✘ PHÁT HIỆN SỰ CỐ:[/bold red]\n{result.message}", title="Audit Integrity", border_style="red"))
        security.log_audit(user, command, "FAIL")
        if result.data:
            console.print(f"Chi tiết kỹ thuật: {result.data}")


def wal_status_cmd():
    """Kiểm tra trạng thái WAL (Write-Ahead Log)."""
    command = "wal-status"
    user = enforce_security(command)
    print_banner("WAL Status")
    
    store_path = Path.cwd() / "store"
    wal = WALManager(store_path)
    status = wal.get_journal_status()
    
    table = Table(title="WAL Journal Status")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Journal Path", status["journal_path"])
    table.add_row("Exists", "✔ Yes" if status["exists"] else "✘ No")
    table.add_row("Total Entries", str(status["total_entries"]))
    table.add_row("Dangling Transactions", str(status["dangling_count"]))
    
    if status["dangling_transactions"]:
        table.add_row("Dangling IDs", "\n".join([f"{id[:16]}..." for id in status["dangling_transactions"]]))
    
    console.print(table)
    
    if status["dangling_count"] > 0:
        console.print(Panel(
            f"[yellow]⚠ Có {status['dangling_count']} transaction bị crash chưa được rollback.[/yellow]\n"
            "Chạy [cyan]sbackup init[/cyan] để tự động recovery.",
            border_style="yellow"
        ))
    else:
        console.print("[green]✔ WAL clean - Không có transaction nào bị crash.[/green]")
    
    security.log_audit(user, command, "OK")


def wal_recover_cmd():
    """Thực hiện WAL Recovery thủ công."""
    command = "wal-recover"
    user = enforce_security(command)
    print_banner("WAL Recovery")
    
    store_path = Path.cwd() / "store"
    wal = WALManager(store_path)
    
    dangling = wal.get_dangling_transactions()
    
    if not dangling:
        console.print("[green]✔ Không có transaction nào cần rollback.[/green]")
        security.log_audit(user, command, "OK")
        return
    
    console.print(f"[yellow]Tìm thấy {len(dangling)} transaction bị crash:[/yellow]")
    for snap_id in dangling:
        console.print(f"   - {snap_id[:16]}...")
    
    # Confirm trước khi rollback
    if typer.confirm("Bạn có muốn rollback các transaction này?"):
        recovered = wal.recover()
        console.print(f"[green]✔ Đã rollback {recovered} transaction.[/green]")
        security.log_audit(user, command, "OK")
    else:
        console.print("[yellow]Đã hủy.[/yellow]")
        security.log_audit(user, command, "CANCELLED")
