import hashlib
import time
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from sbackup.contracts import OpResult

LOG_FILE_PATH = Path(__file__).parent.parent / 'store' / 'audit.log'

def _calculate_sha256(data_string):
    return hashlib.sha256(data_string.encode('utf-8')).hexdigest()

def _ensure_log_dir_exists(filepath):
    directory = os.path.dirname(filepath)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

def get_last_entry_hash(filepath=LOG_FILE_PATH):
    if not os.path.exists(filepath):
        return "0" * 64
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            if not lines: return "0" * 64
            last_line = lines[-1].strip()
            if not last_line: return "0" * 64
            parts = last_line.split(' ')
            return parts[0] if len(parts) > 0 else "0" * 64
    except Exception:
        return "0" * 64

def log_audit(user, full_command, status, filepath=LOG_FILE_PATH) -> OpResult:
    try:
        _ensure_log_dir_exists(filepath)

        parts = full_command.strip().split()
        if not parts:
            return OpResult(success=False, message="Empty command provided.")
            
        command_name = parts[0]
        args_str = " ".join(parts[1:]) if len(parts) > 1 else ""
        args_sha256 = _calculate_sha256(args_str)

        prev_hash = get_last_entry_hash(filepath)
        unix_ms = str(int(time.time() * 1000))

        content_to_hash = f"{prev_hash} {unix_ms} {user} {command_name} {args_sha256} {status}"
        entry_hash = _calculate_sha256(content_to_hash)

        log_line = f"{entry_hash} {content_to_hash}\n"

        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(log_line)
            
        return OpResult(success=True, message="Audit log appended successfully.", data={"entry_hash": entry_hash})

    except Exception as e:
        return OpResult(success=False, message=f"Error writing to audit log: {str(e)}")

def verify_audit_log(filepath=LOG_FILE_PATH) -> OpResult:
    if not os.path.exists(filepath):
        return OpResult(success=False, message="Audit log file does not exist.")

    print(f"Verifying audit log at: {filepath}...")
    
    expected_prev_hash = "0" * 64
    line_number = 0

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line_number += 1
                line = line.strip()
                if not line: continue

                parts = line.split(' ')
                if len(parts) < 7:
                    return OpResult(
                        success=False, 
                        message=f"AUDIT CORRUPTED at line {line_number}: Malformed format."
                    )

                current_entry_hash = parts[0]
                current_prev_hash = parts[1]
                content_to_hash = " ".join(parts[1:])

                # Chain Integrity
                if current_prev_hash != expected_prev_hash:
                    return OpResult(
                        success=False,
                        message=f"AUDIT CORRUPTED at line {line_number}: Broken hash chain.",
                        data={"expected": expected_prev_hash, "found": current_prev_hash}
                    )

                # Data Integrity
                calculated_hash = _calculate_sha256(content_to_hash)
                if calculated_hash != current_entry_hash:
                    return OpResult(
                        success=False,
                        message=f"AUDIT CORRUPTED at line {line_number}: Data modified.",
                        data={"calculated": calculated_hash, "stored": current_entry_hash}
                    )

                expected_prev_hash = current_entry_hash

        return OpResult(
            success=True, 
            message=f"AUDIT OK. Verified {line_number} lines.",
            data={"head_hash": expected_prev_hash}
        )

    except Exception as e:
        return OpResult(success=False, message=f"Error reading audit log: {str(e)}")