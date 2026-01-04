import os
import time
import hashlib
from typing import List
from ..contracts import FileEntry, SnapshotManifest
from ..interfaces import IStorage
from ..config import CHUNK_SIZE
from .utils import chunk_file_content, compute_merkle_root


class BasicLogic:
    """A minimal ILogic-like implementation that relies on an external IStorage.

    Responsibilities implemented here:
    - chunk_data(file_path): split file into chunks, save into storage, return list of chunk hashes
    - create_manifest(label, root_path): walk `root_path`, build manifest and compute merkle root
    - verify_merkle(manifest): recompute merkle root from manifest and compare
    """

    def __init__(self, storage: IStorage):
        self.storage = storage
        self.chunk_size = CHUNK_SIZE

    def chunk_data(self, file_path: str) -> List[str]:
        hashes: List[str] = []
        # Read whole file and use chunk_file_content to produce ChunkEntry list.
        # Note: reading full file into memory; acceptable for current scope.
        with open(file_path, "rb") as f:
            content = f.read()

        entries = chunk_file_content(content)
        for e in entries:
            start = e.offset
            length = e.length
            part = content[start : start + length]
            try:
                self.storage.save_chunk(e.hash, part)
            except Exception:
                # swallow storage errors here; caller should handle operation result
                pass
            hashes.append(e.hash)

        return hashes

    def create_manifest(self, label: str, root_path: str) -> SnapshotManifest:
        files: List[FileEntry] = []
        for dirpath, _, filenames in os.walk(root_path):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root_path).replace("\\", "/")
                stat = os.stat(full)
                chunks = self.chunk_data(full)
                files.append(FileEntry(path=rel, size=stat.st_size, mtime=stat.st_mtime, chunks=chunks))

        files.sort(key=lambda f: f.path)
        manifest = SnapshotManifest(version="1.0", snapshot_id="", created_at=int(time.time() * 1000), label=label, files=files, merkle_root="")

        # Compute per-file hashes and Merkle root
        per_file_hashes: List[str] = []
        for f in manifest.files:
            s = f.path + ":" + ",".join(f.chunks)
            per_file_hashes.append(hashlib.sha256(s.encode("utf-8")).hexdigest())

        merkle = compute_merkle_root(per_file_hashes)
        manifest.merkle_root = merkle
        manifest.snapshot_id = merkle
        return manifest

    def verify_merkle(self, manifest: SnapshotManifest) -> bool:
        per_file_hashes: List[str] = []
        for f in sorted(manifest.files, key=lambda x: x.path):
            # Verify each chunk exists and its content matches the recorded hash
            for ch in f.chunks:
                try:
                    data = self.storage.get_chunk(ch)
                except Exception:
                    return False
                if hashlib.sha256(data).hexdigest() != ch:
                    return False

            s = f.path + ":" + ",".join(f.chunks)
            per_file_hashes.append(hashlib.sha256(s.encode("utf-8")).hexdigest())

        computed = compute_merkle_root(per_file_hashes)
        return computed == manifest.merkle_root
