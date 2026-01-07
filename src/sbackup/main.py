import typer

# Import commands từ module commands
from .commands import (
    backup_cmd,
    verify_cmd,
    restore_cmd,
    init_cmd,
    list_snapshots_cmd,
    audit_verify_cmd,
)

# --- SETUP ---
app = typer.Typer(help="Secure Backup CLI - Lab Project", add_completion=False)

# --- REGISTER COMMANDS ---
app.command(name="init")(init_cmd)
app.command(name="backup")(backup_cmd)
app.command(name="list-snapshots")(list_snapshots_cmd)
app.command(name="verify")(verify_cmd)
app.command(name="restore")(restore_cmd)
app.command(name="audit-verify")(audit_verify_cmd)

if __name__ == "__main__":
    app()
