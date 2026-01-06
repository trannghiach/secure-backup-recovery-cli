from typing import List, Union, Optional
import hashlib
import json
from dataclasses import asdict
from ..contracts import ChunkEntry, SnapshotManifest
from ..config import CHUNK_SIZE


def compute_merkle_root(list_of_hashes: List[Union[str, bytes]]) -> str:
    """Compute a deterministic Merkle root from a list of hex-string or bytes hashes.

    Uses SHA-256, pairs adjacent nodes, concatenates (left||right) and hashes the result.
    If the number of nodes is odd, the last node is duplicated.
    Returns the hex digest (lowercase) of the root.
    For empty input returns sha256(b'').hexdigest().
    """
    if not list_of_hashes:
        return hashlib.sha256(b"").hexdigest()

    # Normalize to bytes
    nodes: List[bytes] = []
    for h in list_of_hashes:
        if isinstance(h, str):
            nodes.append(bytes.fromhex(h))
        else:
            nodes.append(h)

    while len(nodes) > 1:
        next_level: List[bytes] = []
        for i in range(0, len(nodes), 2):
            left = nodes[i]
            right = nodes[i + 1] if i + 1 < len(nodes) else nodes[i]
            combined = left + right
            next_level.append(hashlib.sha256(combined).digest())
        nodes = next_level

    return nodes[0].hex()


def create_canonical_manifest(data: Union[SnapshotManifest, dict]) -> str:
    """Return a deterministic JSON string for the manifest.

    - Ensures `files` list is sorted by `path` ascending.
    - Keeps chunk lists in their original order.
    - Uses JSON with sorted object keys and compact separators so encoding is deterministic.
    """
    if isinstance(data, SnapshotManifest):
        obj = asdict(data)
    else:
        obj = dict(data)

    files = obj.get("files", [])
    normalized_files = []
    for f in files:
        if hasattr(f, "__dict__"):
            normalized_files.append(dict(f.__dict__))
        else:
            normalized_files.append(dict(f))

    normalized_files.sort(key=lambda x: x.get("path", ""))
    obj["files"] = normalized_files

    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def chunk_file_content(content: bytes, chunk_size: Optional[int] = None) -> List[ChunkEntry]:
    """Split `content` into fixed-size chunks and return list of ChunkEntry.

    Each ChunkEntry contains SHA-256 hex hash, offset, and length.
    Default chunk size is 1 MiB.
    """
    if chunk_size is None:
        chunk_size = CHUNK_SIZE

    chunks: List[ChunkEntry] = []
    total = len(content)
    offset = 0
    while offset < total:
        part = content[offset: offset + chunk_size]
        h = hashlib.sha256(part).hexdigest()
        chunks.append(ChunkEntry(hash=h, offset=offset, length=len(part)))
        offset += len(part)
    return chunks
