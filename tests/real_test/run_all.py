"""
Chạy tất cả các test trong real_test/
"""

import os
import sys
import subprocess
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent

# Tìm tất cả file test_*.py
test_files = sorted(TEST_DIR.glob("test_*.py"))

print(f"Found {len(test_files)} tests\n")

for test_file in test_files:
    print(f"=" * 60)
    print(f"Running: {test_file.name}")
    print(f"=" * 60)
    
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    subprocess.run(
        [sys.executable, str(test_file)],
        cwd=TEST_DIR,
        env=env
    )
    print()

