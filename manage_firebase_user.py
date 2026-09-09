import os
import sys
import firebase_admin
from firebase_admin import credentials, auth
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

from app.core.config import settings

def init_firebase():
    if not firebase_admin._apps:
        cred_dict = settings.get_firebase_credential_dict()
        if not cred_dict:
            print("[ERROR] Cannot find Firebase credentials in .env")
            sys.exit(1)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        print("[OK] Firebase Admin SDK initialized.")

def create_or_update_user(email: str, password: str, display_name: str = "Super Admin"):
    init_firebase()
    try:
        user = auth.get_user_by_email(email)
        print(f"[INFO] User {email} already exists (UID: {user.uid}). Updating password...")
        auth.update_user(
            user.uid,
            password=password,
            display_name=display_name,
            email_verified=True
        )
        print(f"[SUCCESS] Password updated for: {email}")
    except auth.UserNotFoundError:
        print(f"[INFO] User {email} not found. Creating new user...")
        user = auth.create_user(
            email=email,
            password=password,
            display_name=display_name,
            email_verified=True
        )
        print(f"[SUCCESS] User created! UID: {user.uid}, Email: {user.email}")
    except Exception as e:
        print(f"[ERROR] {e}")

def list_users():
    init_firebase()
    print("\n--- Firebase Users List ---")
    page = auth.list_users()
    count = 0
    while page:
        for user in page.users:
            count += 1
            name = (user.display_name or "").encode('ascii', errors='replace').decode('ascii')
            print(f"{count}. UID: {user.uid} | Email: {user.email} | Name: {name}")
        page = page.get_next_page()
    if count == 0:
        print("No users found.")
    print("---------------------------")

if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "superadmin@medicalink.com"
    password = sys.argv[2] if len(sys.argv) > 2 else "SuperAdmin123!"
    display_name = sys.argv[3] if len(sys.argv) > 3 else "Super Admin"

    print(f"Creating/updating account: {email} ...")
    create_or_update_user(email, password, display_name)
    list_users()
