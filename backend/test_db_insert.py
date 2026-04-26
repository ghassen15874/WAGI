import uuid
from datetime import datetime
from kilo.server.db import get_conn

def test_insert():
    with get_conn() as conn:
        user_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        try:
            conn.execute(
                """
                INSERT INTO users (
                    id, email, password_hash, github_id, github_username,
                    github_connected, github_installation_id, role, is_active, created_at, updated_at
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    user_id,
                    "test_github_insert@example.com",
                    "",
                    "123456",
                    "testuser",
                    True,
                    None,
                    "USER",
                    True,
                    now,
                    now,
                ),
            )
            config_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO pipeline_configs (id, user_id) VALUES (%s,%s)",
                (config_id, user_id),
            )
            conn.commit()
            print("Insert succeeded!")
        except Exception as e:
            print("Insert failed:", e)

test_insert()
