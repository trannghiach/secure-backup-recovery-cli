import sys
import os
from pathlib import Path

# Đảm bảo import đúng cấu trúc project
sys.path.append(str(Path(__file__).parent.parent))

# from src.sbackup.security.policy import get_current_user, check_permission
# from src.sbackup.security.audit import log_audit, verify_audit_log
from src.sbackup.security.manager import SecurityManager

if __name__ == "__main__":
    security_mgr = SecurityManager()
    while True:
        print("=====================================================")
        choice = input("Choose an action: \n(1) Test Permission and Audit Log \n(2) Test Audit Log Verification \n(0) Exit\nEnter choice: ")
        
        if choice == '1':
            # Định danh
            user = security_mgr.get_current_user()
            print(f"Current OS user: {user}")
            command = input("Enter command (e.g., backup): ")

            # Check Policy
            perm_result = security_mgr.check_permission(user, command)
            
            status = ""
            if not perm_result.success:
                status = "DENY"
                print(f"Permission check: {status} ({perm_result.message})")
            else:
                # Trường hợp được phép -> Giả lập kết quả thực thi (OK hoặc FAIL)
                print(f"Permission check: GRANTED ({perm_result.message})")
                sim_success = input("Simulate execution success? (y/n): ").strip().lower()
                status = "OK" if sim_success == 'y' else "FAIL"

            # Ghi Audit Log (Cập nhật logic OpResult)
            print(f"Appending to audit log with status: {status}...")
            log_result = security_mgr.log_audit(user, command, status)
            
            if log_result.success:
                print(f"Log saved. Hash: {log_result.data.get('entry_hash')}")
            else:
                print(f"Log failed: {log_result.message}")
            
            # Verify audit ngay lập tức (Cập nhật logic OpResult)
            print("\n--- Running Audit Verification ---")
            v_res = security_mgr.verify_audit_log()
            if v_res.success:
                print(f"Quick Verify: {v_res.message}")
            else:
                print(f"Quick Verify: {v_res.message}")

        elif choice == '2':
            print("\n--- Audit Verification ---")
            result = security_mgr.verify_audit_log()
            
            if result.success:
                print(f"AUDIT OK: {result.message}")
                if result.data:
                    print(f"Head Hash: {result.data.get('head_hash')}")
            else:
                print(f"AUDIT ERROR: {result.message}")
                if result.data:
                    print(f"Details: {result.data}")
            
            print("\n--- Audit log verification completed ---\n")

        elif choice == '0':
            print("Exiting.")
            sys.exit(0)
            
        else:
            print("Invalid choice. Please enter 1, 2 or 0.")