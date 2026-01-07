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

---

## 3. Cách tính Merkle Root

```
1. Sắp xếp files theo path (alphabetical)
2. Với mỗi file, tính: file_hash = SHA256(path + ":" + chunk1,chunk2,...)
3. Xây dựng Merkle Tree từ danh sách file_hash:
   - Nếu lẻ node -> duplicate node cuối
   - parent = SHA256(left_bytes + right_bytes)
4. merkle_root = root của tree (hex string)
```

**Ví dụ:**
```
Files (đã sort): a.txt (chunks: abc), b.txt (chunks: def)
file_hash_a = SHA256("a.txt:abc")  
file_hash_b = SHA256("b.txt:def")
merkle_root = SHA256(bytes.fromhex(file_hash_a) + bytes.fromhex(file_hash_b)).hex()
```

---

## 4. Cơ chế chống Rollback

### Nguyên lý
- `snapshot_id` được tính từ `merkle_root`
- Filename = `<snapshot_id>.json`
- Verify kiểm tra 3 điều kiện:
  1. `snapshot_id` trong JSON == filename
  2. `merkle_root` == `snapshot_id`
  3. Tính lại merkle từ chunks == `merkle_root`

### Reproduce Rollback Test

```bash
python tests/real_test/test_wal_rollback.py
```

**Kịch bản test:**
1. Tạo 2 backup A, B
2. Swap filename: A.json <-> B.json
3. Verify A -> FAIL (snapshot_id không khớp filename)

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
python tests/real_test/test_wal_crash.py
```

**Kịch bản test:**
1. Ghi BEGIN vào WAL (không COMMIT)
2. Chạy `init` -> tự động recovery
3. Verify các snapshot cũ vẫn valid

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

```bash
# Chạy tất cả test
python tests/real_test/run_all.py

# Chạy từng test riêng
python tests/real_test/test_restore.py      # Test restore & compare
python tests/real_test/test_tamper_data.py  # Test sửa chunk
python tests/real_test/test_tamper_meta.py  # Test sửa metadata
python tests/real_test/test_wal_rollback.py # Test chống rollback
python tests/real_test/test_wal_crash.py    # Test crash recovery
python tests/real_test/test_policy.py       # Test phân quyền
python tests/real_test/test_audit_tamper.py # Test audit log
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

