import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from ..core.storage import StorageManager
from ..core.logic import BasicLogic
from ..security.manager import SecurityManager

console = Console()

# Khởi tạo các thành phần
storage = StorageManager("store")
logic = BasicLogic(storage)
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


def backup_cmd(
    source: str = typer.Argument(..., help="Thư mục cần backup"), 
    label: str = typer.Option(..., "--label", "-l", help="Nhãn mô tả bản backup")
):
    """Sao lưu dữ liệu (Backup)."""
    command = f"backup {source} {label}"
    user = enforce_security(command)
    
    print_banner(f"Backup Job: {source}")
    console.print(f"User: [cyan]{user}[/cyan] | Label: [yellow]{label}[/yellow]")

    try:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
            progress.add_task(description="Đang phân tích và cắt chunk...", total=None)
            manifest = logic.create_manifest(label, source)
            
            progress.add_task(description="Đang ghi manifest...", total=None)
            storage.save_manifest(manifest)

        console.print(Panel(
            f"Snapshot ID: [bold green]{manifest.snapshot_id}[/bold green]\n"
            f"Merkle Root: [cyan]{manifest.merkle_root}[/cyan]\n"
            f"Files: {len(manifest.files)}",
            title="✔ BACKUP SUCCESS",
            border_style="green"
        ))
        security.log_audit(user, command, "OK")

    except Exception as e:
        console.print(f"[bold red]✘ BACKUP FAILED:[/bold red] {e}")
        security.log_audit(user, command, "FAIL")


def verify_cmd(snapshot_id: str = typer.Argument(..., help="ID của snapshot cần kiểm tra")):
    """Kiểm tra tính toàn vẹn (Verify Integrity)."""
    command = f"verify {snapshot_id}"
    user = enforce_security(command)
    print_banner(f"Verifying Snapshot: {snapshot_id}")

    try:
        try:
            manifest = storage.load_manifest(snapshot_id)
        except FileNotFoundError:
            console.print(f"[bold red]✘ Lỗi: Không tìm thấy snapshot {snapshot_id}[/bold red]")
            security.log_audit(user, command, "FAIL")
            return

        with console.status("[bold blue]Đang kiểm tra Hash & Merkle Tree...[/bold blue]"):
            is_valid = logic.verify_merkle(manifest)

        if is_valid:
            console.print(Panel("[bold green]✔ INTEGRITY CONFIRMED[/bold green]\nDữ liệu toàn vẹn, không bị sửa đổi.", border_style="green"))
            security.log_audit(user, command, "OK")
        else:
            console.print(Panel("[bold red]✘ INTEGRITY CHECK FAILED[/bold red]\nCẢNH BÁO: Dữ liệu trên đĩa không khớp với Manifest (Merkle Root sai lệch).", border_style="red"))
            security.log_audit(user, command, "FAIL")

    except Exception as e:
        console.print(f"[bold red]✘ Lỗi hệ thống: {e}[/bold red]")
        security.log_audit(user, command, "FAIL")


def restore_cmd(
    snapshot_id: str = typer.Argument(..., help="ID snapshot"), 
    target: str = typer.Argument(..., help="Thư mục đích để bung file")
):
    """Phục hồi dữ liệu (Restore)."""
    command = f"restore {snapshot_id} {target}"
    user = enforce_security(command)
    print_banner(f"Restore: {snapshot_id} -> {target}")

    result = storage.restore(snapshot_id, target)

    if result.success:
        console.print(f"[bold green]✔ {result.message}[/bold green]")
        security.log_audit(user, command, "OK")
    else:
        console.print(Panel(f"[bold red]RESTORE FAILED[/bold red]\n{result.message}", style="red"))
        security.log_audit(user, command, "FAIL")
