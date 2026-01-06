import os
import sys
import platform
import getpass
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from sbackup.contracts import OpResult

PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_POLICY_PATH = PROJECT_ROOT / 'policy.yaml'

def get_current_user():
    system = platform.system()
    
    # Linux/Unix logic
    if system in ('Linux', 'Darwin'):
        try:
            import pwd
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
            return None

    # Fallback
    try:
        return getpass.getuser()
    except Exception:
        return None

def load_policy(policy_path: str = None) -> OpResult:
    if policy_path is None:
        policy_path = str(DEFAULT_POLICY_PATH)
    
    if not os.path.exists(policy_path):
        return OpResult(success=False, message=f"Policy file not found at {policy_path}")
    
    with open(policy_path, 'r') as f:
        try:
            config = yaml.safe_load(f)
            return OpResult(success=True, message="Policy loaded", data=config)
        except yaml.YAMLError as e:
            return OpResult(success=False, message=f"Error parsing policy YAML: {str(e)}")

def check_permission(user: str, cmd: str, policy_path: str = None) -> OpResult:
    if not user:
        return OpResult(success=False, message="User identity could not be determined.")
    
    # 1. Load Policy
    load_result = load_policy(policy_path)
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