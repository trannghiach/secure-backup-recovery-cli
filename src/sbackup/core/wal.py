"""
Write-Ahead Logging (WAL) Module
================================
Đảm bảo tính Nguyên tử (Atomicity) cho các thao tác Backup.

Workflow:
1. BEGIN <snapshot_id>  - Ghi log trước khi bắt đầu backup
2. Ghi chunks + manifest xuống đĩa
3. COMMIT <snapshot_id> - Ghi log khi hoàn tất

Nếu crash giữa chừng (có BEGIN nhưng không có COMMIT),
hệ thống sẽ tự động rollback khi khởi động lại.
"""

import os
import time
from pathlib import Path
from typing import List, Set, Tuple
from rich.console import Console

console = Console()


class WALManager:
    """
    Quản lý Write-Ahead Log để đảm bảo Crash Consistency.
    """
    
    # Transaction Actions
    ACTION_BEGIN = "BEGIN"
    ACTION_COMMIT = "COMMIT"
    
    def __init__(self, store_path: Path):
        """
        Args:
            store_path: Đường dẫn đến thư mục store (VD: ./store)
        """
        self.store_path = Path(store_path)
        self.journal_path = self.store_path / "journal.wal"
        self.snapshots_dir = self.store_path / "snapshots"
        self.chunks_dir = self.store_path / "chunks"
    
    def _safe_write(self, filepath: Path, content: str, mode: str = 'a'):
        """
        Ghi dữ liệu xuống đĩa với đảm bảo fsync.
        
        Args:
            filepath: Đường dẫn file
            content: Nội dung cần ghi
            mode: 'a' (append) hoặc 'w' (overwrite)
        """
        # Đảm bảo thư mục tồn tại
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        with open(filepath, mode, encoding='utf-8') as f:
            f.write(content)
            f.flush()                    # Đẩy từ Python buffer xuống OS buffer
            os.fsync(f.fileno())         # Đẩy từ OS buffer xuống đĩa vật lý
    
    def _get_timestamp(self) -> int:
        """Lấy Unix timestamp (milliseconds)."""
        return int(time.time() * 1000)
    
    def begin_transaction(self, snapshot_id: str) -> bool:
        """
        Ghi log BEGIN trước khi bắt đầu backup.
        
        Args:
            snapshot_id: ID của snapshot sắp được tạo
            
        Returns:
            True nếu ghi log thành công
        """
        try:
            timestamp = self._get_timestamp()
            log_entry = f"{timestamp} {self.ACTION_BEGIN} {snapshot_id}\n"
            self._safe_write(self.journal_path, log_entry)
            return True
        except Exception as e:
            console.print(f"[red]WAL Error (BEGIN): {e}[/red]")
            return False
    
    def commit_transaction(self, snapshot_id: str) -> bool:
        """
        Ghi log COMMIT sau khi backup hoàn tất.
        
        Args:
            snapshot_id: ID của snapshot đã được tạo thành công
            
        Returns:
            True nếu ghi log thành công
        """
        try:
            timestamp = self._get_timestamp()
            log_entry = f"{timestamp} {self.ACTION_COMMIT} {snapshot_id}\n"
            self._safe_write(self.journal_path, log_entry)
            return True
        except Exception as e:
            console.print(f"[red]WAL Error (COMMIT): {e}[/red]")
            return False
    
    def _parse_journal(self) -> List[Tuple[int, str, str]]:
        """
        Đọc và parse file journal.
        
        Returns:
            List of (timestamp, action, snapshot_id)
        """
        entries = []
        
        if not self.journal_path.exists():
            return entries
        
        try:
            with open(self.journal_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    parts = line.split(' ', 2)
                    if len(parts) >= 3:
                        timestamp = int(parts[0])
                        action = parts[1]
                        snapshot_id = parts[2]
                        entries.append((timestamp, action, snapshot_id))
        except Exception as e:
            console.print(f"[yellow]WAL Warning: Cannot parse journal: {e}[/yellow]")
        
        return entries
    
    def get_dangling_transactions(self) -> Set[str]:
        """
        Tìm các transaction bị crash (có BEGIN nhưng không có COMMIT).
        
        Returns:
            Set of snapshot_ids bị crash
        """
        entries = self._parse_journal()
        active_transactions: Set[str] = set()
        
        for timestamp, action, snapshot_id in entries:
            if action == self.ACTION_BEGIN:
                active_transactions.add(snapshot_id)
            elif action == self.ACTION_COMMIT:
                active_transactions.discard(snapshot_id)
        
        return active_transactions
    
    def rollback_transaction(self, snapshot_id: str) -> bool:
        """
        Rollback một transaction bị crash.
        Xóa manifest file của snapshot đó.
        
        Args:
            snapshot_id: ID của snapshot cần rollback
            
        Returns:
            True nếu rollback thành công
        """
        try:
            # Xóa manifest file
            manifest_path = self.snapshots_dir / f"{snapshot_id}.json"
            if manifest_path.exists():
                manifest_path.unlink()
                console.print(f"[yellow]   -> Đã xóa manifest rác: {snapshot_id[:16]}...[/yellow]")
            
            # Optional: Có thể xóa chunks liên quan
            # Nhưng do chunk được deduplicate nên rủi ro xóa nhầm
            # -> Chỉ xóa manifest là đủ an toàn
            
            return True
        except Exception as e:
            console.print(f"[red]Rollback Error: {e}[/red]")
            return False
    
    def recover(self) -> int:
        """
        Quét journal và rollback tất cả transaction bị crash.
        Gọi hàm này khi khởi động hệ thống.
        
        Returns:
            Số lượng transaction đã được rollback
        """
        dangling = self.get_dangling_transactions()
        
        if not dangling:
            return 0
        
        console.print(f"[yellow]⚠ WAL Recovery: Phát hiện {len(dangling)} transaction bị crash[/yellow]")
        
        rollback_count = 0
        for snapshot_id in dangling:
            if self.rollback_transaction(snapshot_id):
                rollback_count += 1
        
        # Ghi log ROLLBACK để đánh dấu đã xử lý
        # (Optional: có thể thêm ACTION_ROLLBACK nếu cần audit)
        
        if rollback_count > 0:
            console.print(f"[green]✔ WAL Recovery: Đã rollback {rollback_count} transaction[/green]")
            # Xóa WAL sau khi đã rollback tất cả - không còn transaction nào cần theo dõi
            if self.journal_path.exists():
                self.journal_path.unlink()
                console.print(f"[green]   -> Đã dọn dẹp WAL journal[/green]")
        
        return rollback_count
    
    def compact_journal(self):
        """
        Dọn dẹp journal file - xóa các entries đã COMMIT.
        Giữ lại các entries chưa hoàn thành (nếu có).
        
        Gọi định kỳ để tránh journal phình to.
        """
        dangling = self.get_dangling_transactions()
        
        if not dangling:
            # Không có transaction nào đang chạy -> xóa journal
            if self.journal_path.exists():
                self.journal_path.unlink()
        else:
            # Có transaction đang chạy -> chỉ giữ lại BEGIN của chúng
            entries = self._parse_journal()
            remaining = []
            for timestamp, action, snapshot_id in entries:
                if action == self.ACTION_BEGIN and snapshot_id in dangling:
                    remaining.append(f"{timestamp} {action} {snapshot_id}\n")
            
            # Ghi lại journal với chỉ các entries cần thiết
            self._safe_write(self.journal_path, ''.join(remaining), mode='w')
    
    def get_journal_status(self) -> dict:
        """
        Lấy trạng thái của journal (dùng cho debug/monitoring).
        
        Returns:
            Dict chứa thông tin journal
        """
        entries = self._parse_journal()
        dangling = self.get_dangling_transactions()
        
        return {
            "journal_path": str(self.journal_path),
            "exists": self.journal_path.exists(),
            "total_entries": len(entries),
            "dangling_transactions": list(dangling),
            "dangling_count": len(dangling),
        }


# --- Atomic File Write Helper ---

def atomic_write_file(filepath: Path, content: str, encoding: str = 'utf-8'):
    """
    Ghi file một cách atomic bằng cách:
    1. Ghi vào file .tmp
    2. Fsync
    3. Rename sang tên thật
    
    Đảm bảo file không bao giờ bị corrupt giữa chừng.
    
    Args:
        filepath: Đường dẫn file đích
        content: Nội dung cần ghi
        encoding: Encoding (mặc định utf-8)
    """
    filepath = Path(filepath)
    tmp_path = filepath.with_suffix(filepath.suffix + '.tmp')
    
    # Đảm bảo thư mục tồn tại
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # Bước 1: Ghi vào file tạm
        with open(tmp_path, 'w', encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        
        # Bước 2: Atomic rename (trên cùng filesystem, rename là atomic)
        os.replace(tmp_path, filepath)
        
        # Bước 3: Fsync thư mục cha để đảm bảo rename được ghi xuống đĩa
        # (Quan trọng trên Linux/Unix, Windows tự động sync)
        try:
            dir_fd = os.open(str(filepath.parent), os.O_RDONLY | os.O_DIRECTORY)
            os.fsync(dir_fd)
            os.close(dir_fd)
        except (OSError, AttributeError):
            # Windows không support O_DIRECTORY, bỏ qua
            pass
            
    except Exception as e:
        # Dọn dẹp file tạm nếu có lỗi
        if tmp_path.exists():
            tmp_path.unlink()
        raise e


def atomic_write_bytes(filepath: Path, data: bytes):
    """
    Ghi file binary một cách atomic.
    
    Args:
        filepath: Đường dẫn file đích
        data: Dữ liệu bytes cần ghi
    """
    filepath = Path(filepath)
    tmp_path = filepath.with_suffix(filepath.suffix + '.tmp')
    
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(tmp_path, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        
        os.replace(tmp_path, filepath)
        
        try:
            dir_fd = os.open(str(filepath.parent), os.O_RDONLY | os.O_DIRECTORY)
            os.fsync(dir_fd)
            os.close(dir_fd)
        except (OSError, AttributeError):
            pass
            
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink()
        raise e
