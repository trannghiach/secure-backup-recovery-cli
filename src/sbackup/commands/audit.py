import typer
from rich.console import Console
from rich.panel import Panel

from ..security.manager import SecurityManager

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
