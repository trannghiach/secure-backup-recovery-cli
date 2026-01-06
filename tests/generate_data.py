import os
import random
import string
from pathlib import Path
from rich.console import Console

console = Console()

def create_dummy_file(path: Path, size_kb: int):
    """Tạo 1 file với nội dung ngẫu nhiên"""
    # Sinh chuỗi ngẫu nhiên để nội dung không bị trùng (tránh dedup quá sớm)
    content = ''.join(random.choices(string.ascii_letters + string.digits, k=1024))
    
    with open(path, "w") as f:
        # Lặp lại chuỗi để đạt kích thước mong muốn
        for _ in range(size_kb):
            f.write(content)

def generate_dataset(root_dir: str = "dataset_test", num_files: int = 50, max_size_kb: int = 1024):
    """Tạo bộ dataset test"""
    root = Path(root_dir)
    if root.exists():
        console.print(f"[yellow]⚠ Thư mục {root_dir} đã tồn tại. Bỏ qua tạo mới.[/yellow]")
        return

    os.makedirs(root, exist_ok=True)
    console.print(f"[bold green]Đang sinh {num_files} files ngẫu nhiên vào {root_dir}...[/bold green]")

    for i in range(num_files):
        file_name = f"file_{i:03d}.txt"
        # Random size từ 1KB đến max_size_kb
        size = random.randint(1, max_size_kb) 
        create_dummy_file(root / file_name, size)
        
    console.print(f"[bold green]✔ Đã tạo xong dataset tại {root_dir}[/bold green]")

if __name__ == "__main__":
    generate_dataset()