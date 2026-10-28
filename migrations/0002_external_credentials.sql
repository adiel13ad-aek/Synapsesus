-- Credential references contain no password, provider key or session token.
CREATE TABLE IF NOT EXISTS credential_cleanup (
  credential TEXT PRIMARY KEY,
  not_before INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_operation_locks (
  user_id TEXT PRIMARY KEY REFERENCES actors(id) ON DELETE CASCADE,
  owner TEXT NOT NULL,
  expires INTEGER NOT NULL
);
