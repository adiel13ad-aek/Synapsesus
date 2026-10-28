PRAGMA foreign_keys=ON;
CREATE TABLE actors (
 id TEXT PRIMARY KEY, handle TEXT NOT NULL UNIQUE COLLATE NOCASE,
 name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('human','ai')),
 bio TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT 'blue',
 owner_id TEXT REFERENCES actors(id) ON DELETE CASCADE,
 password_hash TEXT, seeded INTEGER NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
, email TEXT NOT NULL DEFAULT '', email_verified INTEGER NOT NULL DEFAULT 0, avatar_path TEXT NOT NULL DEFAULT '', cover_path TEXT NOT NULL DEFAULT '', website TEXT NOT NULL DEFAULT '', interests TEXT NOT NULL DEFAULT '[]', theme TEXT NOT NULL DEFAULT 'system', accent TEXT NOT NULL DEFAULT 'violet', reduce_motion INTEGER NOT NULL DEFAULT 0, dm_policy TEXT NOT NULL DEFAULT 'everyone', terms_version TEXT NOT NULL DEFAULT '', account_private INTEGER NOT NULL DEFAULT 0, age_band TEXT NOT NULL DEFAULT 'unknown', age_verified_until REAL NOT NULL DEFAULT 0, age_provider TEXT NOT NULL DEFAULT '');
CREATE TABLE sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 csrf TEXT NOT NULL, expires REAL NOT NULL
);
CREATE TABLE missions (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 agent_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 title TEXT NOT NULL, goal TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL
);
CREATE TABLE posts (
 id TEXT PRIMARY KEY, author_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 body TEXT NOT NULL, source TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
 approved_by TEXT REFERENCES actors(id) ON DELETE CASCADE,
 mission_id TEXT REFERENCES missions(id) ON DELETE SET NULL, created_at TEXT NOT NULL
, link_url TEXT NOT NULL DEFAULT '', link_title TEXT NOT NULL DEFAULT '', image_path TEXT NOT NULL DEFAULT '', image_alt TEXT NOT NULL DEFAULT '', hidden INTEGER NOT NULL DEFAULT 0);
CREATE TABLE comments (
 id TEXT PRIMARY KEY, post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
 author_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 body TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE likes (
 user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE, PRIMARY KEY(user_id,post_id)
);
CREATE TABLE bookmarks (
 user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE, PRIMARY KEY(user_id,post_id)
);
CREATE TABLE follows (
 user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 target_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE, PRIMARY KEY(user_id,target_id)
);
CREATE TABLE blocks (
 user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 target_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE, PRIMARY KEY(user_id,target_id)
);
CREATE TABLE messages (
 id TEXT PRIMARY KEY, sender_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 recipient_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 body TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'human', model TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE drafts (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 agent_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 body TEXT NOT NULL, source TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
 mission_id TEXT REFERENCES missions(id) ON DELETE SET NULL,
 status TEXT NOT NULL DEFAULT 'pending', post_id TEXT REFERENCES posts(id) ON DELETE SET NULL, created_at TEXT NOT NULL
);
CREATE TABLE audit (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 action TEXT NOT NULL, subject_id TEXT NOT NULL, summary TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE reports (
 id TEXT PRIMARY KEY, reporter_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 post_id TEXT REFERENCES posts(id) ON DELETE SET NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
, status TEXT NOT NULL DEFAULT 'open');
CREATE TABLE usage (
 user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 day TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,day)
);
CREATE TABLE global_usage (day TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE web_links (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 url TEXT NOT NULL, title TEXT NOT NULL, collection TEXT NOT NULL DEFAULT 'Favoritos',
 note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, UNIQUE(owner_id,url)
);
CREATE TABLE search_usage (
 user_id TEXT NOT NULL, day TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,day)
);
CREATE TABLE search_global_usage (day TEXT PRIMARY KEY,count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE auth_tokens (
 token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 purpose TEXT NOT NULL CHECK(purpose IN ('verify','reset')), expires REAL NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE stories (
 id TEXT PRIMARY KEY,author_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 body TEXT NOT NULL,image_path TEXT NOT NULL DEFAULT '',color TEXT NOT NULL DEFAULT 'violet',created_at TEXT NOT NULL,expires REAL NOT NULL
);
CREATE TABLE notifications (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 actor_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,kind TEXT NOT NULL,target_id TEXT NOT NULL,
 seen INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,UNIQUE(user_id,actor_id,kind,target_id)
);
CREATE TABLE content_reports (
 id TEXT PRIMARY KEY,reporter_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 kind TEXT NOT NULL,target_id TEXT NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',created_at TEXT NOT NULL
);
CREATE TABLE media_assets (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 post_id TEXT REFERENCES posts(id) ON DELETE CASCADE,
 position INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL CHECK(kind IN ('image','video')),
 path TEXT NOT NULL UNIQUE, thumbnail TEXT NOT NULL DEFAULT '', bytes INTEGER NOT NULL,
 width INTEGER NOT NULL, height INTEGER NOT NULL, duration REAL NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL
);
CREATE TABLE operators (user_id TEXT PRIMARY KEY REFERENCES actors(id) ON DELETE CASCADE, created_at TEXT NOT NULL);
CREATE TABLE push_subscriptions (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 endpoint TEXT NOT NULL UNIQUE, p256dh TEXT NOT NULL, auth TEXT NOT NULL, created_at TEXT NOT NULL,
 last_attempt REAL NOT NULL DEFAULT 0, delivered_through TEXT NOT NULL DEFAULT '', failures INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE calls (
 id TEXT PRIMARY KEY, caller_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
 callee_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE, mode TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'ringing', created_at TEXT NOT NULL, expires REAL NOT NULL
);
CREATE TABLE call_signals (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
 sender_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE, payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE operator_roles (
        user_id TEXT PRIMARY KEY REFERENCES operators(user_id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK(role IN ('owner','moderator')));
CREATE TABLE operator_security (
        user_id TEXT PRIMARY KEY REFERENCES operators(user_id) ON DELETE CASCADE,
        secret TEXT NOT NULL DEFAULT '', pending TEXT NOT NULL DEFAULT '', pending_expires REAL NOT NULL DEFAULT 0,
        enabled INTEGER NOT NULL DEFAULT 0, last_step INTEGER NOT NULL DEFAULT -1,
        recovery_hashes TEXT NOT NULL DEFAULT '[]');
CREATE TABLE admin_grants (
        token_hash TEXT PRIMARY KEY REFERENCES sessions(token_hash) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE, expires REAL NOT NULL);
CREATE TABLE site_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), registration_open INTEGER NOT NULL DEFAULT 0,
        maintenance INTEGER NOT NULL DEFAULT 0, uploads_enabled INTEGER NOT NULL DEFAULT 1,
        announcement TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
CREATE TABLE admin_events (
        id TEXT PRIMARY KEY, actor_id TEXT REFERENCES actors(id) ON DELETE SET NULL,
        actor_label TEXT NOT NULL, action TEXT NOT NULL, target_type TEXT NOT NULL,
        target_id TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE site_policies (
        kind TEXT PRIMARY KEY, body TEXT NOT NULL, reviewed_by TEXT REFERENCES actors(id) ON DELETE SET NULL,
        reviewed_at TEXT NOT NULL);
CREATE TABLE launch_attestations (
        name TEXT PRIMARY KEY, actor_id TEXT REFERENCES actors(id) ON DELETE SET NULL,
        note TEXT NOT NULL, origin TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE durable_rates (
        key_hash TEXT PRIMARY KEY, bucket INTEGER NOT NULL, count INTEGER NOT NULL, expires REAL NOT NULL);
CREATE TABLE pilot_invites (
              id TEXT PRIMARY KEY, code_hash TEXT UNIQUE NOT NULL,
              label TEXT NOT NULL, created_by TEXT REFERENCES actors(id) ON DELETE SET NULL,
              max_uses INTEGER NOT NULL, uses INTEGER NOT NULL DEFAULT 0,
              expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL);
CREATE TABLE follow_requests (
      requester_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
      target_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
      created_at TEXT NOT NULL, PRIMARY KEY(requester_id,target_id));
CREATE TABLE session_devices (
      id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL REFERENCES sessions(token_hash) ON DELETE CASCADE,
      created_at TEXT NOT NULL, device TEXT NOT NULL);
CREATE TABLE age_challenges (
      challenge_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
      expires REAL NOT NULL);
CREATE TABLE guardian_invites (
      token_hash TEXT PRIMARY KEY, child_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
      email_hash TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE guardianships (
      child_id TEXT PRIMARY KEY REFERENCES actors(id) ON DELETE CASCADE,
      guardian_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
      paused INTEGER NOT NULL DEFAULT 0, accepted_at TEXT NOT NULL,
      CHECK(child_id != guardian_id));
CREATE TABLE support_tickets (
      id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
      kind TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'open', reply TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE policy_reviews (kind TEXT PRIMARY KEY REFERENCES site_policies(kind) ON DELETE CASCADE, release TEXT NOT NULL, body_hash TEXT NOT NULL, reviewed_at TEXT NOT NULL);
CREATE TABLE integration_checks (
      name TEXT PRIMARY KEY, origin TEXT NOT NULL, checked_at REAL NOT NULL, detail TEXT NOT NULL, fingerprint TEXT NOT NULL DEFAULT '');
CREATE TABLE mail_jobs (
      id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
      purpose TEXT NOT NULL, token_hash TEXT NOT NULL DEFAULT '', encrypted_message TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
      next_attempt REAL NOT NULL, expires REAL NOT NULL, lease_until REAL NOT NULL DEFAULT 0,
      error_code TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, completed_at TEXT NOT NULL DEFAULT '');
CREATE TABLE backup_jobs (
      id TEXT PRIMARY KEY, requested_by TEXT REFERENCES actors(id) ON DELETE SET NULL,
      status TEXT NOT NULL, file_name TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL DEFAULT '',
      bytes INTEGER NOT NULL DEFAULT 0, remote_key TEXT NOT NULL DEFAULT '', error_code TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, completed_at TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL DEFAULT '');
CREATE INDEX posts_time ON posts(created_at DESC);
CREATE INDEX comments_post ON comments(post_id,created_at);
CREATE INDEX messages_thread ON messages(sender_id,recipient_id,created_at);
CREATE INDEX draft_owner ON drafts(owner_id,status);
CREATE INDEX audit_owner ON audit(owner_id,created_at DESC);
CREATE INDEX web_links_owner ON web_links(owner_id,collection,created_at DESC);
CREATE INDEX stories_expiration ON stories(expires);
CREATE INDEX notifications_user ON notifications(user_id,created_at DESC);
CREATE INDEX media_post ON media_assets(post_id,position);
CREATE INDEX signals_call ON call_signals(call_id,seq);
CREATE UNIQUE INDEX actors_email ON actors(email COLLATE NOCASE) WHERE email <> '';
CREATE INDEX admin_events_date ON admin_events(created_at DESC);
CREATE INDEX pilot_invites_expiry ON pilot_invites(expires);
CREATE INDEX guardian_accounts ON guardianships(guardian_id);
CREATE INDEX support_open ON support_tickets(status,created_at);
CREATE INDEX followers_target ON follows(target_id,user_id);
CREATE INDEX blocks_target ON blocks(target_id,user_id);
CREATE INDEX likes_post ON likes(post_id,user_id);
CREATE INDEX sessions_user ON sessions(user_id,expires);
CREATE INDEX mail_due ON mail_jobs(status,next_attempt);
CREATE TRIGGER notify_like AFTER INSERT ON likes
WHEN (SELECT author_id FROM posts WHERE id=NEW.post_id) != NEW.user_id
BEGIN
 INSERT OR IGNORE INTO notifications SELECT lower(hex(randomblob(16))),p.author_id,NEW.user_id,'like',NEW.post_id,0,strftime('%Y-%m-%dT%H:%M:%fZ','now') FROM posts p WHERE p.id=NEW.post_id;
END;
CREATE TRIGGER notify_follow AFTER INSERT ON follows BEGIN
 INSERT OR IGNORE INTO notifications VALUES(lower(hex(randomblob(16))),NEW.target_id,NEW.user_id,'follow',NEW.user_id,0,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
END;
CREATE TRIGGER notify_comment AFTER INSERT ON comments
WHEN (SELECT author_id FROM posts WHERE id=NEW.post_id)!=NEW.author_id
BEGIN
 INSERT OR IGNORE INTO notifications SELECT lower(hex(randomblob(16))),p.author_id,NEW.author_id,'comment',NEW.id,0,NEW.created_at FROM posts p WHERE p.id=NEW.post_id;
END;
CREATE TRIGGER notify_message AFTER INSERT ON messages BEGIN
 INSERT OR IGNORE INTO notifications VALUES(lower(hex(randomblob(16))),NEW.recipient_id,NEW.sender_id,'message',NEW.id,0,NEW.created_at);
END;
INSERT INTO site_settings VALUES(1,0,0,1,'',strftime('%Y-%m-%dT%H:%M:%fZ','now'));
CREATE TABLE setup_locks(id INTEGER PRIMARY KEY CHECK(id=1),user_id TEXT UNIQUE NOT NULL,consumed_at TEXT NOT NULL);
CREATE TABLE media_cleanup(path TEXT PRIMARY KEY,created_at TEXT NOT NULL);
