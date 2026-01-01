from dataclasses import dataclass, field
from typing import List, Optional, Dict

# Định nghĩa cấu trúc Chunk (đề bài: content-addressable storage)
@dataclass
class ChunkEntry:
    hash: str       # SHA-256
    offset: int
    length: int     # Fixed 1MB

# Định nghĩa cấu trúc File trong Manifest
@dataclass
class FileEntry:
    path: str       # Relative path
    size: int
    mtime: float
    chunks: List[str]  # List of chunk hashes
    
# Định nghĩa Snapshot Manifest (JSON Canonical)
@dataclass
class SnapshotManifest:
    version: str = "1.0"
    snapshot_id: str = ""
    created_at: int = 0  # Unix timestamp ms
    label: str = ""
    files: List[FileEntry] = field(default_factory=list)
    merkle_root: str = "" 
    prev_snapshot_id: Optional[str] = None # Chống rollback

# Kết quả trả về chuẩn cho mọi hàm logic
@dataclass
class OpResult:
    success: bool
    message: str
    data: Optional[Dict] = None