import sys
import typer
from click.exceptions import UsageError

# Import commands từ module commands
from .commands import (
    backup_cmd,
    verify_cmd,
    restore_cmd,
    init_cmd,
    list_snapshots_cmd,
    audit_verify_cmd,
)

# Import Security Manager
from .security.manager import SecurityManager

# --- SETUP ---
app = typer.Typer(help="Secure Backup CLI - Lab Project", add_completion=False)
security = SecurityManager()

# --- REGISTER COMMANDS ---
app.command(name="init")(init_cmd)
app.command(name="backup")(backup_cmd)
app.command(name="list-snapshots")(list_snapshots_cmd)
app.command(name="verify")(verify_cmd)
app.command(name="restore")(restore_cmd)
app.command(name="audit-verify")(audit_verify_cmd)

def main():
    """Main wrapper với exception handling để bắt lệnh không hợp lệ."""
    # Lấy thông tin command trước khi chạy
    argv_parts = sys.argv[1:] if len(sys.argv) > 1 else []
    
    try:
        app()
    except (SystemExit, Exception) as e:
        # Ghi log cho lệnh không hợp lệ TRƯỚC KHI re-raise
        if argv_parts:
            try:
                security.log_invalid_command(argv_parts)
            except:
                pass  # Đảm bảo không làm gián đoạn flow
        
        # Re-raise để Typer hiển thị error message
        raise

if __name__ == "__main__":
    main()
