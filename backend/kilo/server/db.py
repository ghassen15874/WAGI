"""
Database client — uses PostgreSQL via psycopg2 pool.
Auto-initializes schema on startup for easy deployment.
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool

# We fall back to the lovable user on localhost if not specified in .env
DB_URL = os.getenv("DATABASE_URL", "postgresql://lovable:lovable123@localhost:5432/lovable")

_pool = None
_last_pool_error = ""

def init_pool(*, raise_on_error: bool = False):
    global _pool
    global _last_pool_error
    if _pool is None:
        try:
            _pool = SimpleConnectionPool(1, 20, DB_URL)
            _last_pool_error = ""
        except Exception as e:
            _last_pool_error = str(e)
            print(f"⚠️ Failed to connect to PostgreSQL: {e}")
            if raise_on_error:
                raise RuntimeError(
                    "PostgreSQL is required for the platform backend, but the connection failed. "
                    f"Configured DATABASE_URL: {DB_URL}"
                ) from e


def get_last_db_error() -> str:
    return _last_pool_error


def ensure_db_ready() -> None:
    init_pool(raise_on_error=True)
    conn = None
    try:
        conn = _pool.getconn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception as e:
        global _last_pool_error
        _last_pool_error = str(e)
        raise RuntimeError(
            "PostgreSQL is configured but not reachable. "
            "Start PostgreSQL or set DATABASE_URL to a working instance."
        ) from e
    finally:
        if conn is not None and _pool is not None:
            _pool.putconn(conn)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id           VARCHAR(255) PRIMARY KEY,
    email        VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    github_id    VARCHAR(255),
    github_username VARCHAR(255) NOT NULL DEFAULT '',
    github_connected BOOLEAN NOT NULL DEFAULT FALSE,
    github_installation_id BIGINT,
    role         VARCHAR(50) NOT NULL DEFAULT 'USER',
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS api_keys (
    id            VARCHAR(255) PRIMARY KEY,
    user_id       VARCHAR(255) NOT NULL,
    provider      VARCHAR(100) NOT NULL,
    encrypted_key TEXT NOT NULL,
    label         VARCHAR(255) NOT NULL DEFAULT '',
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pipeline_configs (
    id                   VARCHAR(255) PRIMARY KEY,
    user_id              VARCHAR(255) UNIQUE NOT NULL,
    clear_sandbox_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    design_system_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    system_prompt_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    self_healing_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    summary_enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    use_shared_models    BOOLEAN NOT NULL DEFAULT TRUE,
    shared_models        TEXT NOT NULL DEFAULT '',
    planning_model       VARCHAR(255) NOT NULL DEFAULT '',
    architecture_model   VARCHAR(255) NOT NULL DEFAULT '',
    frontend_model       VARCHAR(255) NOT NULL DEFAULT '',
    backend_model        VARCHAR(255) NOT NULL DEFAULT '',
    validation_model     VARCHAR(255) NOT NULL DEFAULT '',
    updated_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS logs (
    id         VARCHAR(255) PRIMARY KEY,
    user_id    VARCHAR(255),
    event      VARCHAR(255) NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    level      VARCHAR(50) NOT NULL DEFAULT 'info',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id            VARCHAR(255) PRIMARY KEY,
    user_id       VARCHAR(255) NOT NULL,
    name          VARCHAR(255) NOT NULL DEFAULT 'Untitled Project',
    github_repo_url TEXT NOT NULL DEFAULT '',
    github_repo_name VARCHAR(255) NOT NULL DEFAULT '',
    github_deploy_status VARCHAR(50) NOT NULL DEFAULT 'IDLE',
    github_deploy_error TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS provider_registry (
    id         VARCHAR(100) PRIMARY KEY,
    name       VARCHAR(255) NOT NULL,
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS model_registry (
    id          VARCHAR(255) PRIMARY KEY,
    model_id    VARCHAR(255) NOT NULL,
    provider_id VARCHAR(100) NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order  INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    FOREIGN KEY (provider_id) REFERENCES provider_registry(id) ON DELETE CASCADE
);
"""

_ALTER_SQL = """
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS max_iter INT NOT NULL DEFAULT 70;
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS max_healing_attempts INT NOT NULL DEFAULT 20;
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS active_memory_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS builder_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS auto_install_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS project_build_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS integration_test_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS linter_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS runtime_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS feature_validator_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS clear_sandbox_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS design_system_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS system_prompt_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS summary_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS use_shared_models BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE pipeline_configs ADD COLUMN IF NOT EXISTS shared_models TEXT NOT NULL DEFAULT '';

ALTER TABLE users ADD COLUMN IF NOT EXISTS github_id VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS github_username VARCHAR(255) NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS github_connected BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS github_installation_id BIGINT;

ALTER TABLE projects ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'IDLE';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_narration TEXT NOT NULL DEFAULT '';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS error_message TEXT NOT NULL DEFAULT '';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS github_repo_url TEXT NOT NULL DEFAULT '';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS github_repo_name VARCHAR(255) NOT NULL DEFAULT '';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS github_deploy_status VARCHAR(50) NOT NULL DEFAULT 'IDLE';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS github_deploy_error TEXT NOT NULL DEFAULT '';

ALTER TABLE provider_registry ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;
ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;
ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS model_id VARCHAR(255);
CREATE UNIQUE INDEX IF NOT EXISTS users_github_id_idx ON users (github_id) WHERE github_id IS NOT NULL;
"""

_DEFAULT_PROVIDERS = [
    {"id": "auto", "name": "Auto-Routing"},
    {"id": "groq", "name": "Groq"},
    {"id": "anthropic", "name": "Anthropic Claude"},
    {"id": "openai", "name": "OpenAI"},
    {"id": "openrouter", "name": "OpenRouter"},
    {"id": "deepseek", "name": "DeepSeek API"},
    {"id": "scraper", "name": "Self-hosted Gateway"},
]

_DEFAULT_MODELS = [
    {"model_id": "llama-3.3-70b-versatile", "provider_id": "groq"},
    {"model_id": "llama-3.1-70b-versatile", "provider_id": "groq"},
    {"model_id": "mixtral-8x7b-32768", "provider_id": "groq"},
    {"model_id": "openai/gpt-oss-120b", "provider_id": "groq"},
    {"model_id": "qwen/qwen3-32b", "provider_id": "groq"},
    {"model_id": "claude-3-5-haiku-latest", "provider_id": "anthropic"},
    {"model_id": "claude-3-5-sonnet-latest", "provider_id": "anthropic"},
    {"model_id": "claude-sonnet-4-20250514", "provider_id": "anthropic"},
    {"model_id": "gpt-4o", "provider_id": "openai"},
    {"model_id": "gpt-4o-mini", "provider_id": "openai"},
    {"model_id": "gpt-5.4-mini", "provider_id": "openai"},
    {"model_id": "gpt-3.5-turbo", "provider_id": "openai"},
    {"model_id": "anthropic/claude-3.5-sonnet", "provider_id": "openrouter"},
    {"model_id": "meta-llama/llama-3.3-70b-instruct", "provider_id": "openrouter"},
    {"model_id": "deepseek-chat", "provider_id": "deepseek"},
    {"model_id": "deepseek-reasoner", "provider_id": "deepseek"},
    {"model_id": "chatgpt", "provider_id": "scraper"},
    {"model_id": "deepseek", "provider_id": "scraper"},
    {"model_id": "deepseek-chat", "provider_id": "scraper"},
    {"model_id": "gemini", "provider_id": "scraper"},
    {"model_id": "gpt-4o", "provider_id": "scraper"},
    {"model_id": "gpt-4o-mini", "provider_id": "scraper"},
    {"model_id": "gemini-2.0-flash", "provider_id": "scraper"},
    {"model_id": "groq", "provider_id": "scraper"},
]


def _registry_key(provider_id: str, model_id: str) -> str:
    return f"{provider_id}:{model_id}"


def _migrate_model_registry(cur):
    cur.execute(
        """
        UPDATE model_registry
        SET model_id = CASE
            WHEN position(':' in id) > 0 THEN split_part(id, ':', 2)
            ELSE id
        END
        WHERE model_id IS NULL OR model_id = ''
        """
    )
    cur.execute(
        """
        UPDATE model_registry
        SET id = provider_id || ':' || model_id
        WHERE position(':' in id) = 0
          AND NOT EXISTS (
              SELECT 1
              FROM model_registry existing
              WHERE existing.id = model_registry.provider_id || ':' || model_registry.model_id
          )
        """
    )
    cur.execute(
        """
        DELETE FROM model_registry legacy
        USING model_registry canonical
        WHERE legacy.provider_id = canonical.provider_id
          AND legacy.model_id = canonical.model_id
          AND legacy.id <> canonical.id
          AND canonical.id = canonical.provider_id || ':' || canonical.model_id
          AND position(':' in legacy.id) = 0
        """
    )
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS model_registry_provider_model_idx
        ON model_registry (provider_id, model_id)
        """
    )


def _seed_registry(cur):
    for index, provider in enumerate(_DEFAULT_PROVIDERS):
        cur.execute(
            """
            INSERT INTO provider_registry (id, name, enabled, sort_order)
            VALUES (%s, %s, TRUE, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                sort_order = EXCLUDED.sort_order,
                updated_at = NOW()
            """,
            (provider["id"], provider["name"], index),
        )

    for index, model in enumerate(_DEFAULT_MODELS):
        registry_id = _registry_key(model["provider_id"], model["model_id"])
        cur.execute(
            """
            INSERT INTO model_registry (id, model_id, provider_id, enabled, sort_order)
            VALUES (%s, %s, %s, TRUE, %s)
            ON CONFLICT (id) DO UPDATE SET
                model_id = EXCLUDED.model_id,
                provider_id = EXCLUDED.provider_id,
                sort_order = EXCLUDED.sort_order,
                updated_at = NOW()
            """,
            (registry_id, model["model_id"], model["provider_id"], index),
        )

class CursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor
        
    def execute(self, query, params=None):
        self.cursor.execute(query, params)
        return self

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def close(self):
        try:
            self.cursor.close()
        except: pass

class ConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn
        self._cursors = []
        
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def execute(self, query, params=None):
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        cw = CursorWrapper(cursor)
        self._cursors.append(cw)
        cw.execute(query, params)
        return cw

    def commit(self):
        self.conn.commit()

    def rollback(self):
        if self.conn:
            self.conn.rollback()
        
    def close(self):
        # Close all tracked cursors
        for cw in self._cursors:
            cw.close()
        self._cursors = []
        
        if _pool and self.conn:
            _pool.putconn(self.conn)
            self.conn = None

def get_conn() -> ConnectionWrapper:
    init_pool()
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Is PostgreSQL running?")
    try:
        conn = _pool.getconn()
        return ConnectionWrapper(conn)
    except psycopg2.pool.PoolError:
        # Emergency: if pool is exhausted, let's try to clear it or wait
        import time
        time.sleep(0.5)
        conn = _pool.getconn()
        return ConnectionWrapper(conn)

def init_db():
    init_pool()
    if _pool:
        conn = _pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA_SQL)
                cur.execute(_ALTER_SQL)
                _migrate_model_registry(cur)
                _seed_registry(cur)
            conn.commit()
        except Exception as e:
            print(f"⚠️ Failed to init schema: {e}")
            conn.rollback()
        finally:
            _pool.putconn(conn)

# Just to stop IDE complaining
def row_to_dict(row) -> dict: return dict(row) if row else None
def rows_to_list(rows) -> list: return [dict(r) for r in rows] if rows else []

# Only attempt init if not being imported by certain auto-tools
init_db()
