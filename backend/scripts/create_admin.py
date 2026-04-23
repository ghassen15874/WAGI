"""
Script to create a default admin user for the WAGI platform.
"""
import uuid
import bcrypt
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kilo.server.db import get_conn

def create_admin(email, password):
    email = email.lower().strip()
    conn = get_conn()
    try:
        # Check if exists
        existing = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
        if existing:
            print(f"User {email} already exists. Updating role to ADMIN.")
            conn.execute("UPDATE users SET role='ADMIN' WHERE email=%s", (email,))
            conn.commit()
            return

        user_id = str(uuid.uuid4())
        pw_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        now = datetime.utcnow().isoformat()
        
        conn.execute(
            "INSERT INTO users (id, email, password_hash, role, is_active, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (user_id, email, pw_hash, "ADMIN", True, now, now),
        )
        
        # Auto-create empty pipeline config
        config_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO pipeline_configs (id, user_id) VALUES (%s,%s)",
            (config_id, user_id),
        )
        
        conn.commit()
        print(f"✅ Admin user created: {email}")
        print(f"🔑 Password: {password}")
    finally:
        conn.close()

if __name__ == "__main__":
    create_admin("admin@wagi.ai", "admin123")
