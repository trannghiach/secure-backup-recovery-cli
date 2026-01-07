import os
import sys
import time
import yaml
import hashlib
import platform
import getpass
from pathlib import Path
from typing import Dict, Optional

from ..contracts import OpResult
from ..config import POLICY_FILE, get_audit_log_path

# Import Interface
from ..interfaces import ISecurity

class SecurityManager:
    """
    Security Manager hợp nhất:
    - Logic xác thực User (từ policy.py cũ)
    - Logic check quyền (từ policy.py cũ)
    - Logic Audit Log (từ audit.py cũ)
    """

    def __init__(self):
        # Cache policy để không phải đọc file nhiều lần
        self._policy_cache = None

    # --- PRIVATE HELPERS ---

    def _calculate_sha256(self, data_string: str) -> str:
        return hashlib.sha256(data_string.encode('utf-8')).hexdigest()

    def _ensure_log_dir_exists(self, filepath):
        directory = os.path.dirname(filepath)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

    def get_last_entry_hash(self, filepath=None):
        if filepath is None:
            filepath = get_audit_log_path()
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

    def load_policy(self, policy_path: str = None) -> OpResult:
        if policy_path is None:
            policy_path = str(POLICY_FILE)
        
        if not os.path.exists(policy_path):
            return OpResult(success=False, message=f"Policy file not found at {policy_path}")
        
        with open(policy_path, 'r') as f:
            try:
                config = yaml.safe_load(f)
                return OpResult(success=True, message="Policy loaded", data=config)
            except yaml.YAMLError as e:
                return OpResult(success=False, message=f"Error parsing policy YAML: {str(e)}")

    # --- PUBLIC INTERFACE (ISecurity Implementation) ---

    def get_current_user(self) -> str:
        system = platform.system()
        
        # Linux/Unix logic
        if system in ('Linux', 'Darwin'):
            try:
                current_uid = os.getuid()
                sudo_user = os.environ.get('SUDO_USER')
                if sudo_user: return sudo_user
                if current_uid == 0: return 'SUDO_ROOT'
            except (ImportError, AttributeError):
                pass
        
        # Windows logic
        if system == 'Windows':
            try:
                username = getpass.getuser()
                domain = os.environ.get('USERDOMAIN', 'ANONYMOUS')
                return f"{domain}\\{username}"
            except Exception:
                return "unknown"

    def check_permission(self, user: str, cmd: str, policy_path: str = None) -> OpResult:
        if not user:
            return OpResult(success=False, message="User identity could not be determined.")
        
        # 1. Load Policy
        load_result = self.load_policy(policy_path)
        if not load_result.success:
            return load_result
        
        config = load_result.data
        
        # 2. Parse Command
        parts = cmd.strip().split()
        if not parts:
            return OpResult(success=False, message="Empty command.")
        command = parts[0]
        
        # 3. Check User Role
        user_role = config.get('users', {}).get(user)
        if not user_role:
            return OpResult(success=False, message=f"Access Denied: User '{user}' not found in policy.")
        
        # 4. Check Command in Role
        allowed_commands = config.get('roles', {}).get(user_role, [])
        
        if command in allowed_commands:
            return OpResult(success=True, message=f"Access Granted: User '{user}' can run '{command}'.")
        else:
            return OpResult(
                success=False, 
                message=f"Access Denied: Role '{user_role}' is not allowed to run '{command}'."
            )

    def log_audit(self, user, full_command, status, filepath=None) -> OpResult:
        try:
            if filepath is None:
                filepath = get_audit_log_path()
            self._ensure_log_dir_exists(filepath)

            parts = full_command.strip().split()
            if not parts:
                return OpResult(success=False, message="Empty command provided.")
                
            command_name = parts[0]
            args_str = " ".join(parts[1:]) if len(parts) > 1 else ""
            args_sha256 = self._calculate_sha256(args_str)

            prev_hash = self.get_last_entry_hash(filepath)
            unix_ms = str(int(time.time() * 1000))

            content_to_hash = f"{prev_hash} {unix_ms} {user} {command_name} {args_sha256} {status}"
            entry_hash = self._calculate_sha256(content_to_hash)
            log_line = f"{entry_hash} {content_to_hash}\n"

            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(log_line)
                
            return OpResult(success=True, message="Audit log appended successfully.", data={"entry_hash": entry_hash})

        except Exception as e:
            return OpResult(success=False, message=f"Error writing to audit log: {str(e)}")

    def verify_audit_log(self, filepath=None) -> OpResult:
        if filepath is None:
            filepath = get_audit_log_path()
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
                    calculated_hash = self._calculate_sha256(content_to_hash)
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