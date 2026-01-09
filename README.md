# Secure Backup CLI

Công cụ backup an toàn với tính năng kiểm tra toàn vẹn dữ liệu, phân quyền và audit log.

---

## 1. Hướng dẫn Cài đặt & Chạy

**Yêu cầu:** Python 3.8+

```bash
# 1. Tạo môi trường ảo
python -m venv .venv

# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 2. Cài đặt
pip install -e .
```

**Các lệnh cơ bản:**

```bash
sbackup --help              # Xem trợ giúp
sbackup init                # Khởi tạo kho lưu trữ
sbackup backup <dir> -l "label"   # Backup thư mục
sbackup list-snapshots      # Liệt kê các bản backup
sbackup verify <snapshot_id>      # Kiểm tra toàn vẹn
sbackup restore <snapshot_id> <target>  # Khôi phục dữ liệu
sbackup audit-verify        # Kiểm tra audit log
```

---

## 2. Chunk Size & Canonical Manifest

### Chunk Size
- **Kích thước chunk:** 1MB (1024 * 1024 bytes) - cấu hình trong `config.py`
- File được chia thành các chunk, mỗi chunk được hash SHA-256
- Chunk được lưu tại `store/chunks/<hash>`

### Canonical Manifest (Snapshot)
File JSON tại `store/snapshots/<snapshot_id>.json`:

```json
{
  "version": "1.0",
  "snapshot_id": "<sha256_merkle_root>",
  "created_at": 1767775682318,
  "label": "Backup label",
  "prev_snapshot_id": "<snapshot_trước_hoặc_null>",
  "files": [
    {
      "path": "relative/path/file.txt",
      "size": 1234,
      "mtime": 1767775600.0,
      "chunks": ["<chunk_hash_1>", "<chunk_hash_2>"]
    }
  ],
  "merkle_root": "<sha256_merkle_root>"
}
```

**Quy tắc canonical:**
- Files được sắp xếp theo `path` (alphabetical)
- Path dùng `/` (forward slash)
- `snapshot_id` = `merkle_root` (để chống giả mạo)
- `prev_snapshot_id` = snapshot_id của bản backup trước (Hash Chain)

---

## 3. Cách tính Merkle Root

```
1. Tính metadata_hash = SHA256(version + ":" + label + ":" + created_at + ":" + prev_snapshot_id)
2. Sắp xếp files theo path (alphabetical)
3. Với mỗi file, tính: file_hash = SHA256(path + ":" + chunk1,chunk2,...)
4. Tạo danh sách all_hashes = [metadata_hash, file_hash_1, file_hash_2, ...]
5. Xây dựng Merkle Tree từ all_hashes:
   - Nếu lẻ node -> duplicate node cuối
   - parent = SHA256(left_bytes + right_bytes)
6. merkle_root = root của tree (hex string)
```

**Ví dụ:**
```python
# Metadata
metadata_str = "1.0:My Backup:1767775682318:abc123..."  # prev_snapshot_id hoặc '' nếu không có
metadata_hash = SHA256(metadata_str)

# Files (đã sort)
file_hash_a = SHA256("a.txt:abc")  
file_hash_b = SHA256("b.txt:def")

# Tất cả hashes
all_hashes = [metadata_hash, file_hash_a, file_hash_b]

# Merkle tree từ all_hashes
merkle_root = compute_merkle_root(all_hashes)
```

> **Lưu ý:** Metadata được đưa vào Merkle Root để phát hiện nếu ai đó sửa label, timestamp hoặc prev_snapshot_id.

---

## 4. Cơ chế chống Rollback (Hash Chain)

### Nguyên lý
Mỗi snapshot có trường `prev_snapshot_id` trỏ đến snapshot trước đó, tạo thành **hash chain**:

```
Snapshot 1 (S1)          Snapshot 2 (S2)          Snapshot 3 (S3)
prev_snapshot_id: null   prev_snapshot_id: S1     prev_snapshot_id: S2
       │                        │                        │
       └────────────────────────┴────────────────────────┘
                         Hash Chain
```

### Canonical Manifest với Hash Chain

```json
{
  "version": "1.0",
  "snapshot_id": "<sha256_merkle_root>",
  "created_at": 1767775682318,
  "label": "Backup label",
  "prev_snapshot_id": "<snapshot_id_của_bản_trước>",
  "files": [...],
  "merkle_root": "<sha256_merkle_root>"
}
```

### Phát hiện Rollback

Kẻ tấn công xóa snapshot mới nhất (S3) để "rollback" về S2:

```bash
# Trạng thái ban đầu: S1 <- S2 <- S3
# Sau khi xóa S3: S1 <- S2 (S2 trở thành "mới nhất" giả)

sbackup verify <S2_id>  # -> PASS (S2 vẫn valid)
# Nhưng ta BIẾT đã bị rollback vì:
# - Audit log vẫn ghi nhận S3 từng tồn tại
# - Hoặc kiểm tra số lượng snapshot
```

**Ví dụ verify kiểm tra:**
1. `snapshot_id` trong JSON == filename
2. `merkle_root` == `snapshot_id`
3. Tính lại merkle từ (metadata + chunks) == `merkle_root`
4. `prev_snapshot_id` phải tồn tại (nếu không phải snapshot đầu)

### Reproduce Rollback Test

```bash
python tests/test_rollback.py
```

**Kịch bản test:**
1. Tạo 2 backup: S1 (prev=null), S2 (prev=S1)
2. Xóa S2 (giả lập rollback attack)
3. Kiểm tra: số snapshot giảm = phát hiện rollback

---

## 5. Journal/WAL (Write-Ahead Logging)

### Cơ chế
File `store/journal.wal` ghi log trước khi ghi dữ liệu:

```
<timestamp> BEGIN <snapshot_id>
<timestamp> COMMIT <snapshot_id>
```

**Ví dụ thực tế:**
```
1767775682318 BEGIN c953267d15dcd289688a748582c360b4661197130401037fb079d91310c8b424
1767775682456 COMMIT c953267d15dcd289688a748582c360b4661197130401037fb079d91310c8b424
```

### Quy trình Backup
1. `BEGIN` - Bắt đầu transaction
2. Ghi chunks và manifest
3. `COMMIT` - Đánh dấu hoàn tất

### Recovery
- Khi `init`, hệ thống kiểm tra WAL
- Nếu có transaction không có COMMIT -> rollback (xóa file dở dang)

### Reproduce Crash Test

```bash
python tests/test_crash.py
```

**Kịch bản test:**
1. Backup bình thường (S1) - thành công
2. Inject "bomb" vào code để crash sau BEGIN, trước COMMIT
3. Backup lần 2 - CRASH (có BEGIN nhưng không COMMIT)
4. Chạy `init` -> tự động recovery (xóa file dở dang)
5. Backup lần 3 - thành công
6. Verify tất cả snapshot còn lại -> PASS

---

## 6. Policy & Phân quyền

### Schema policy.yaml

```yaml
users:
  <os_username>: <role>
  DOMAIN\username: admin    # Windows format
  unix_user: operator       # Linux format

roles:
  admin: [init, backup, list-snapshots, verify, restore, audit-verify]
  operator: [backup, list-snapshots, verify, restore, audit-verify]
  auditor: [list-snapshots, verify, audit-verify]
```

### Ví dụ

```yaml
users:
  LAPTOP-ABC\User: operator
  root: admin
  guest: auditor

roles:
  admin: [init, backup, list-snapshots, verify, restore, audit-verify]
  operator: [backup, list-snapshots, verify, restore, audit-verify]
  auditor: [list-snapshots, verify, audit-verify]
```

---

## 7. Audit Log

### Định dạng dòng

```
<entry_hash> <prev_hash> <timestamp> <user> <command> <args_hash> <status>
```

- `entry_hash`: SHA256 của toàn bộ nội dung dòng (trừ chính nó)
- `prev_hash`: entry_hash của dòng trước (dòng đầu = "0" * 64)
- `timestamp`: Unix timestamp (milliseconds)
- `user`: OS username (VD: `WORKGROUP\pwn3dBYf0q5`)
- `command`: Tên lệnh (VD: `init`, `backup`)
- `args_hash`: SHA256 của arguments (VD: hash của "data --label test")
- `status`: `OK`, `FAIL`, hoặc `DENY`

**Ví dụ:**
```
92ca48c1... 00000000... 1767775682318 WORKGROUP\pwn3dBYf0q5 init 824d80d7... OK
457ab29e... 92ca48c1... 1767775682786 WORKGROUP\pwn3dBYf0q5 backup e81411b0... DENY
```

### Cách tính Hash (Hash Chain)

```python
content_to_hash = f"{prev_hash} {timestamp} {user} {command} {args_hash} {status}"
entry_hash = SHA256(content_to_hash)
log_line = f"{entry_hash} {content_to_hash}"
```

- Dòng đầu: `prev_hash = "0" * 64`
- Dòng sau: `prev_hash = entry_hash của dòng trước`

### Chạy Audit-Verify

```bash
sbackup audit-verify
```

Kiểm tra:
1. Hash chain liên tục (prev_hash khớp entry trước)
2. Entry hash được tính đúng
3. Không có dòng bị xóa/sửa

---

## 8. Xác định USER từ OS

### Logic (trong SecurityManager)

```python
def get_current_user():
    # Linux/Unix
    if system in ('Linux', 'Darwin'):
        sudo_user = os.environ.get('SUDO_USER')
        if sudo_user:
            return sudo_user  # Ưu tiên SUDO_USER
        if os.getuid() == 0:
            return 'SUDO_ROOT'
        return getpass.getuser()
    
    # Windows
    if system == 'Windows':
        username = getpass.getuser()
        domain = os.environ.get('USERDOMAIN', 'ANONYMOUS')
        return f"{domain}\\{username}" 
```

**Ưu tiên:**
1. `SUDO_USER` (nếu đang chạy qua sudo)
2. `SUDO_ROOT` (nếu là root không qua sudo)
3. Username thường

---

## 9. Chạy Test

### Danh sách 7 Test Cases (theo yêu cầu bài tập)

| # | Test | Mô tả |
|---|------|-------|
| 1 | `test_restore.py` | Restore & so sánh nội dung với dữ liệu gốc |
| 2 | `test_tamper_data.py` | Sửa chunk → verify FAIL |
| 3 | `test_tamper_meta.py` | Sửa metadata (label/timestamp) → verify FAIL |
| 4 | `test_rollback.py` | Xóa snapshot mới → phát hiện rollback attack |
| 5 | `test_crash.py` | Crash giữa chừng → recovery tự động |
| 6 | `test_policy.py` | DENY command nếu không có quyền + ghi audit |
| 7 | `test_audit_tamper.py` | Sửa audit log → audit-verify FAIL |

### Chạy Test

```bash
# Chạy tất cả 7 test
python tests/run_all.py

# Chạy từng test riêng
python tests/test_restore.py       # 1. Restore & compare
python tests/test_tamper_data.py   # 2. Tamper chunk
python tests/test_tamper_meta.py   # 3. Tamper metadata  
python tests/test_rollback.py      # 4. Rollback detection (Hash Chain)
python tests/test_crash.py         # 5. Crash recovery (WAL)
python tests/test_policy.py        # 6. Policy DENY + audit
python tests/test_audit_tamper.py  # 7. Audit tamper detection
```

---

## 10. Cấu trúc thư mục

```
store/
├── chunks/           # Các chunk dữ liệu (tên = SHA256)
├── snapshots/        # Manifest JSON (tên = merkle_root)
├── journal.wal       # Write-Ahead Log
└── audit.log         # Audit log (hash chain)

src/sbackup/
├── main.py           # CLI entry point
├── config.py         # Cấu hình (chunk size, paths)
├── contracts.py      # Data classes
├── commands/         # CLI commands
├── core/             # Logic chính (storage, logic, wal)
└── security/         # Phân quyền & audit
```

