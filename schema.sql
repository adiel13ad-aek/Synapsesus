PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS actors (
 id TEXT PRIMARY KEY, handle TEXT NOT NULL UNIQUE COLLATE NOCASE,
 name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('human','ai')),
 bio TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT 'blue',
 owner_id TEXT REFERENCES actors(id) ON DELETE CASCADE,
 password_hash TEXT, seeded INTEGER NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 csrf TEXT NOT NULL, expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS missions (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 agent_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 title TEXT NOT NULL, goal TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
 id TEXT PRIMARY KEY, author_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 body TEXT NOT NULL, source TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
 approved_by TEXT REFERENCES actors(id) ON DELETE CASCADE,
 mission_id TEXT REFERENCES missions(id) ON DELETE SET NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
 id TEXT PRIMARY KEY, post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
 author_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 body TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS likes (
 user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE, PRIMARY KEY(user_id,post_id)
);
CREATE TABLE IF NOT EXISTS bookmarks (
 user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE, PRIMARY KEY(user_id,post_id)
);
CREATE TABLE IF NOT EXISTS follows (
 user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 target_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE, PRIMARY KEY(user_id,target_id)
);
CREATE TABLE IF NOT EXISTS blocks (
 user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 target_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE, PRIMARY KEY(user_id,target_id)
);
CREATE TABLE IF NOT EXISTS messages (
 id TEXT PRIMARY KEY, sender_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 recipient_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 body TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'human', model TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 agent_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 body TEXT NOT NULL, source TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
 mission_id TEXT REFERENCES missions(id) ON DELETE SET NULL,
 status TEXT NOT NULL DEFAULT 'pending', post_id TEXT REFERENCES posts(id) ON DELETE SET NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 action TEXT NOT NULL, subject_id TEXT NOT NULL, summary TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
 id TEXT PRIMARY KEY, reporter_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 post_id TEXT REFERENCES posts(id) ON DELETE SET NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
 user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 day TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,day)
);
CREATE INDEX IF NOT EXISTS posts_time ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS comments_post ON comments(post_id,created_at);
CREATE INDEX IF NOT EXISTS messages_thread ON messages(sender_id,recipient_id,created_at);
CREATE INDEX IF NOT EXISTS draft_owner ON drafts(owner_id,status);
CREATE INDEX IF NOT EXISTS audit_owner ON audit(owner_id,created_at DESC);

-- Aggregate limit survives account deletion; it contains no user identifier.
CREATE TABLE IF NOT EXISTS global_usage (day TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0);

-- v0.3: private link collections. Legacy agent tables are retained only for upgrade safety.
CREATE TABLE IF NOT EXISTS web_links (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 url TEXT NOT NULL, title TEXT NOT NULL, collection TEXT NOT NULL DEFAULT 'Favoritos',
 note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, UNIQUE(owner_id,url)
);
CREATE INDEX IF NOT EXISTS web_links_owner ON web_links(owner_id,collection,created_at DESC);
CREATE TABLE IF NOT EXISTS search_usage (
 user_id TEXT NOT NULL, day TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,day)
);
CREATE TABLE IF NOT EXISTS search_global_usage (day TEXT PRIMARY KEY,count INTEGER NOT NULL DEFAULT 0);

-- 0.4 additive tables; actor/post/report column migrations are in initialize().
CREATE TABLE IF NOT EXISTS auth_tokens (
 token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 purpose TEXT NOT NULL CHECK(purpose IN ('verify','reset')), expires REAL NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stories (
 id TEXT PRIMARY KEY,author_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 body TEXT NOT NULL,image_path TEXT NOT NULL DEFAULT '',color TEXT NOT NULL DEFAULT 'violet',created_at TEXT NOT NULL,expires REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS stories_expiration ON stories(expires);
CREATE TABLE IF NOT EXISTS notifications (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 actor_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,kind TEXT NOT NULL,target_id TEXT NOT NULL,
 seen INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,UNIQUE(user_id,actor_id,kind,target_id)
);
CREATE INDEX IF NOT EXISTS notifications_user ON notifications(user_id,created_at DESC);
CREATE TABLE IF NOT EXISTS content_reports (
 id TEXT PRIMARY KEY,reporter_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 kind TEXT NOT NULL,target_id TEXT NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS notify_like AFTER INSERT ON likes
WHEN (SELECT author_id FROM posts WHERE id=NEW.post_id) != NEW.user_id
BEGIN
 INSERT OR IGNORE INTO notifications SELECT lower(hex(randomblob(16))),p.author_id,NEW.user_id,'like',NEW.post_id,0,strftime('%Y-%m-%dT%H:%M:%fZ','now') FROM posts p WHERE p.id=NEW.post_id;
END;
CREATE TRIGGER IF NOT EXISTS notify_follow AFTER INSERT ON follows BEGIN
 INSERT OR IGNORE INTO notifications VALUES(lower(hex(randomblob(16))),NEW.target_id,NEW.user_id,'follow',NEW.user_id,0,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
END;
CREATE TRIGGER IF NOT EXISTS notify_comment AFTER INSERT ON comments
WHEN (SELECT author_id FROM posts WHERE id=NEW.post_id)!=NEW.author_id
BEGIN
 INSERT OR IGNORE INTO notifications SELECT lower(hex(randomblob(16))),p.author_id,NEW.author_id,'comment',NEW.id,0,NEW.created_at FROM posts p WHERE p.id=NEW.post_id;
END;
CREATE TRIGGER IF NOT EXISTS notify_message AFTER INSERT ON messages BEGIN
 INSERT OR IGNORE INTO notifications VALUES(lower(hex(randomblob(16))),NEW.recipient_id,NEW.sender_id,'message',NEW.id,0,NEW.created_at);
END;
