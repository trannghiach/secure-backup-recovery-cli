## Hướng dẫn Cài đặt & Chạy (Installation)

Yêu cầu: Python 3.8+

```bash
# 1. Tạo môi trường ảo (Khuyến nghị)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 2. Cài đặt gói (Dấu chấm nghĩa là thư mục hiện tại)
pip install -e .
```

Sau khi cài đặt xong, có thể dùng lệnh:

```bash
sbackup --help
sbackup init

```

