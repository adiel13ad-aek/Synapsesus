import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import register, { validateAgeReceipt, processMail, launchReadiness, recordIntegration } from '../src/safety.js';
import { sendMail, issueToken, sha256, stamp, encryptSecret } from '../src/core.js';
const routes = new Map(); register({ on(method, path, fn) { routes.set(method + ' ' + path, fn); } });
const route = key => routes.get(key);
const rejects = (p, status) => assert.rejects(p, e => e.status === status);
const b64 = x => Buffer.from(x).toString('base64url');
function fixture(t) {
  const db = new DatabaseSync(':memory:'); db.exec(readFileSync(new URL('../migrations/0001_initial.sql', import.meta.url), 'utf8')); t.after(() => db.close());
  function prepare(sql, args = []) { return { sql, args, bind(...args) { return prepare(sql, args); }, async first() { return db.prepare(sql).get(...args) || null; }, async all() { const results = db.prepare(sql).all(...args); return { results, meta: { changes: db.prepare('SELECT changes() n').get().n } }; }, async run() { const r = db.prepare(sql).run(...args); return { meta: { changes: Number(r.changes) } }; } }; }
  const DB = { prepare, async batch(items) { db.exec('BEGIN IMMEDIATE'); try { const results = items.map(s => { if (/\bRETURNING\b|^\s*(SELECT|PRAGMA)/i.test(s.sql)) { const results = db.prepare(s.sql).all(...s.args); return { results, meta: { changes: db.prepare('SELECT changes() n').get().n } }; } return { meta: { changes: Number(db.prepare(s.sql).run(...s.args).changes) } }; }); db.exec('COMMIT'); return results; } catch (e) { db.exec('ROLLBACK'); throw e; } } };
  const env = { DB, APP_ENV: 'development', AGE_ENFORCED: '0', PUBLIC_ORIGIN: 'https://synapse.example', ADMIN_ENCRYPTION_KEY: b64(Buffer.alloc(32, 7)), MAIL_FROM: 'Synapse <test@example.com>', RESEND_API_KEY: 'test-key', MEDIA: { async delete() {} }, SUPPORT_EMAIL: 'help@example.com' };
  function actor(id = 'alice', overrides = {}) { db.prepare("INSERT INTO actors(id,handle,name,kind,email,email_verified,age_band,age_verified_until,created_at) VALUES(?,?,?,'human',?,1,'adult',?,?)").run(id, id, 'Test ' + id, id + '@example.com', stamp() + 3600, new Date().toISOString()); for (const [k, v] of Object.entries(overrides)) db.prepare(`UPDATE actors SET ${k}=? WHERE id=?`).run(v, id); return { ...db.prepare('SELECT * FROM actors WHERE id=?').get(id), csrf: 'csrf' }; }
  function c(data = {}, user = null, method = 'POST', params = {}) { const request = new Request('http://localhost:8787/api/test', { method, headers: { 'Content-Type': 'application/json' }, ...(method === 'GET' ? {} : { body: JSON.stringify(data) }) }); return { request, url: new URL(request.url), params, env, user, sessionHash: 'current', ctx: { waitUntil() {} }, headers: new Headers() }; }
  return { db, env, actor, c };
}
async function issuer(f) { const pair = await crypto.subtle.generateKey('Ed25519', true, ['sign', 'verify']); f.env.AGE_PUBLIC_KEY = b64(await crypto.subtle.exportKey('raw', pair.publicKey)); f.env.AGE_PROVIDER_ID = 'trusted-test-provider'; f.env.AGE_PROVIDER_URL = 'https://verifier.example/verify'; return async overrides => { const body = b64(JSON.stringify({ v: 1, iss: f.env.AGE_PROVIDER_ID, aud: f.env.PUBLIC_ORIGIN, challenge: 'x'.repeat(43), band: 'adult', iat: stamp(), exp: stamp() + 200, ...overrides })); return body + '.' + b64(await crypto.subtle.sign('Ed25519', pair.privateKey, new TextEncoder().encode(body))); }; }
function mockFetch(t, fn) { const original = globalThis.fetch; globalThis.fetch = fn; t.after(() => { globalThis.fetch = original; }); }

test('signed age receipt verifies signature, exact audience and finite lifetime', async t => {
  const f = fixture(t), sign = await issuer(f);
  assert.equal((await validateAgeReceipt(f.c(), await sign())).band, 'adult');
  for (const bad of [{ aud: 'https://another.example' }, { iss: 'other' }, { exp: stamp() - 1 }, { exp: stamp() + 900 }, { iat: true }, { band: '18' }, { extra: 'value' }]) await rejects(validateAgeReceipt(f.c(), await sign(bad)), 400);
  const receipt = await sign(); await rejects(validateAgeReceipt(f.c(), receipt.slice(0, -5) + 'aaaaa'), 400);
});

test('age challenge belongs to one account, is consumed once, and cannot be replayed', async t => {
  const f = fixture(t), alice = f.actor(), bob = f.actor('bob'), sign = await issuer(f);
  f.db.prepare('INSERT INTO age_challenges VALUES(?,?,?)').run(await sha256('x'.repeat(43)), alice.id, stamp() + 600);
  const receipt = await sign(); await rejects(route('POST /api/account/age/confirm')(f.c({ receipt }, bob)), 400);
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM age_challenges').get().n, 1);
  assert.equal((await route('POST /api/account/age/confirm')(f.c({ receipt }, alice))).band, 'adult');
  await rejects(route('POST /api/account/age/confirm')(f.c({ receipt }, alice)), 400);
  assert.equal(f.db.prepare("SELECT COUNT(*) n FROM integration_checks WHERE name='age_verifier'").get().n, 1);
});

test('minor age result locks privacy and messages and removes existing followers', async t => {
  const f = fixture(t), alice = f.actor(), bob = f.actor('bob'), sign = await issuer(f);
  f.db.prepare('INSERT INTO follows VALUES(?,?)').run(bob.id, alice.id);
  f.db.prepare('INSERT INTO age_challenges VALUES(?,?,?)').run(await sha256('x'.repeat(43)), alice.id, stamp() + 600);
  await route('POST /api/account/age/confirm')(f.c({ receipt: await sign({ band: '16_17' }) }, alice));
  const result = f.db.prepare('SELECT * FROM actors WHERE id=?').get(alice.id);
  assert.equal(result.account_private, 1); assert.equal(result.dm_policy, 'off');
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM follows').get().n, 0);
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM follow_requests').get().n, 1);
  await rejects(route('POST /api/account/guardian/invite')(f.c({ email: bob.email }, result)), 403);
});

test('follower approval cannot bypass a block; follower removal is scoped to current account', async t => {
  const f = fixture(t), alice = f.actor(), bob = f.actor('bob');
  f.db.prepare('INSERT INTO follow_requests VALUES(?,?,?)').run(bob.id, alice.id, new Date().toISOString());
  f.db.prepare('INSERT INTO blocks VALUES(?,?)').run(alice.id, bob.id);
  await rejects(route('POST /api/account/follow-requests/:requester_id')(f.c({ approve: true }, alice, 'POST', { requester_id: bob.id })), 409);
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM follows').get().n, 0);
});

test('session list exposes opaque handles and only owner can revoke', async t => {
  const f = fixture(t), alice = f.actor(), bob = f.actor('bob');
  f.db.prepare('INSERT INTO sessions VALUES(?,?,?,?)').run('current', alice.id, 'csrf', stamp() + 600);
  f.db.prepare('INSERT INTO sessions VALUES(?,?,?,?)').run('other-secret-hash', bob.id, 'csrf2', stamp() + 600);
  const result = await route('GET /api/account/sessions')(f.c({}, alice, 'GET'));
  assert.equal(result.items.length, 1); assert.equal(result.items[0].current, true); assert.equal('token_hash' in result.items[0], false);
  const foreign = await route('GET /api/account/sessions')(f.c({}, bob, 'GET'));
  await rejects(route('DELETE /api/account/sessions/:session_id')(f.c({}, alice, 'DELETE', { session_id: foreign.items[0].id })), 404);
  await rejects(route('DELETE /api/account/sessions/:session_id')(f.c({}, alice, 'DELETE', { session_id: result.items[0].id })), 409);
});

test('support is private to its owner and survives social activation restrictions', async t => {
  const f = fixture(t), alice = f.actor('alice', { email_verified: 0 }), bob = f.actor('bob');
  const ticket = await route('POST /api/account/support')(f.c({ kind: 'appeal', subject: 'Quero uma revisão', body: 'Gostaria de entender e revisar a decisão da equipe.' }, alice));
  assert.ok(ticket.id);
  assert.equal((await route('GET /api/account/support')(f.c({}, alice, 'GET'))).items.length, 1);
  assert.equal((await route('GET /api/account/support')(f.c({}, bob, 'GET'))).items.length, 0);
  await rejects(route('GET /api/manage/support')(f.c({}, bob, 'GET')), 403);
});

test('mail queue cancels obsolete auth links and removes expired payloads without sending', async t => {
  const f = fixture(t), alice = f.actor(); let calls = 0; mockFetch(t, async () => { calls++; return Response.json({ id: 'sent' }); });
  await issueToken(f.c(), alice, 'verify'); f.db.prepare('DELETE FROM auth_tokens').run();
  await sendMail(f.c(), alice.email, 'expired', 'private', { userId: alice.id, expires: stamp() - 1 });
  await processMail(f.c());
  assert.equal(calls, 0);
  const jobs = f.db.prepare('SELECT status,encrypted_message FROM mail_jobs').all();
  assert.deepEqual(jobs.map(j => j.status).sort(), ['cancelled', 'expired']); assert.ok(jobs.every(j => j.encrypted_message === ''));
});

test('mail acceptance clears private contents and does not claim mailbox delivery', async t => {
  const f = fixture(t), alice = f.actor(); let request;
  mockFetch(t, async (url, options) => { request = { url, options }; return Response.json({ id: 'provider-id' }); });
  const id = await sendMail(f.c(), alice.email, 'hello', 'private link token', { userId: alice.id });
  const result = await processMail(f.c()); assert.equal(result.sent, 1); assert.equal(request.url, 'https://api.resend.com/emails');
  assert.equal(request.options.headers['Idempotency-Key'], 'synapse-mail/' + id);
  const job = f.db.prepare('SELECT * FROM mail_jobs').get(); assert.equal(job.status, 'sent'); assert.equal(job.encrypted_message, '');
  const checks = f.db.prepare('SELECT name,detail FROM integration_checks').all(); assert.equal(checks[0].name, 'email_api'); assert.match(checks[0].detail, /não comprova/);
});

test('mail transient failures retry with same idempotency key and redacted error code', async t => {
  const f = fixture(t), alice = f.actor(); const keys = [], payloads = []; let calls = 0;
  mockFetch(t, async (_url, options) => { keys.push(options.headers['Idempotency-Key']); payloads.push(options.body); calls++; return calls === 1 ? new Response('secret recipient debug data', { status: 503 }) : Response.json({ id: 'provider-id' }); });
  await sendMail(f.c(), alice.email, 'hello', 'private link token', { userId: alice.id });
  await processMail(f.c()); let job = f.db.prepare('SELECT * FROM mail_jobs').get(); assert.equal(job.status, 'queued'); assert.equal(job.error_code, 'mail_provider_unavailable');
  f.db.prepare('UPDATE mail_jobs SET next_attempt=0').run(); await processMail(f.c());
  assert.equal(keys.length, 2); assert.equal(keys[0], keys[1]); assert.equal(payloads[0], payloads[1]);
});

test('mail permanent rejection fails without exposing provider response', async t => {
  const f = fixture(t), alice = f.actor(); mockFetch(t, async () => new Response('recipient=private@example.com token=secret', { status: 422 }));
  await sendMail(f.c(), alice.email, 'hello', 'private', { userId: alice.id }); await processMail(f.c());
  const job = f.db.prepare('SELECT * FROM mail_jobs').get(); assert.equal(job.status, 'failed'); assert.equal(job.error_code, 'mail_provider_rejected');
});

test('mail active lease is respected and no provider key is a configuration failure, not success', async t => {
  const f = fixture(t), alice = f.actor(); let calls = 0; mockFetch(t, async () => { calls++; return Response.json({ id: 'sent' }); });
  await sendMail(f.c(), alice.email, 'hello', 'private', { userId: alice.id });
  f.db.prepare("UPDATE mail_jobs SET status='sending',lease_until=?").run(stamp() + 600); await processMail(f.c()); assert.equal(calls, 0);
  delete f.env.RESEND_API_KEY; assert.equal((await processMail(f.c())).configured, false); assert.equal(calls, 0);
});

test('mail retries outside idempotency window stop before reaching provider', async t => {
  const f = fixture(t), alice = f.actor(); let calls = 0; mockFetch(t, async () => { calls++; return Response.json({ id: 'sent' }); });
  await sendMail(f.c(), alice.email, 'hello', 'private', { userId: alice.id, expires: stamp() + 3600 });
  f.db.prepare('UPDATE mail_jobs SET attempts=1,created_at=?').run(new Date(Date.now() - 24 * 3600000).toISOString()); await processMail(f.c());
  assert.equal(calls, 0); assert.equal(f.db.prepare('SELECT error_code FROM mail_jobs').get().error_code, 'mail_retry_window_expired');
});

test('operator attestations cannot fabricate technical integration readiness', async t => {
  const f = fixture(t); f.actor();
  for (const name of ['audience_review', 'email_test', 'backup_restore', 'moderation', 'browser_test']) f.db.prepare('INSERT INTO launch_attestations VALUES(?,?,?,?,?)').run(name, 'alice', 'Test declaration only', f.env.PUBLIC_ORIGIN, new Date().toISOString());
  const result = await launchReadiness(f.c()); assert.equal(result.ready, false);
  assert.equal(result.checks.find(x => x.id === 'email_test').kind, 'operator_attestation');
  assert.equal(result.checks.find(x => x.id === 'email_verification_validated').ok, false);
  assert.equal(result.checks.find(x => x.id === 'age_verifier_validated').ok, false);
});

test('integration evidence expires and changing configuration invalidates it', async t => {
  const f = fixture(t); f.actor(); f.env.TURNSTILE_SITE_KEY = 'site'; f.env.TURNSTILE_SECRET_KEY = 'key';
  await recordIntegration(f.c(), 'turnstile', 'Validated in test');
  assert.equal((await launchReadiness(f.c())).checks.find(x => x.id === 'turnstile_validated').ok, true);
  f.env.TURNSTILE_SECRET_KEY = 'rotated'; assert.equal((await launchReadiness(f.c())).checks.find(x => x.id === 'turnstile_validated').ok, false);
  f.env.TURNSTILE_SECRET_KEY = 'key'; f.db.prepare('UPDATE integration_checks SET checked_at=0').run(); assert.equal((await launchReadiness(f.c())).checks.find(x => x.id === 'turnstile_validated').ok, false);
});

test('launch can become ready only with current policies, integrations, owner MFA and explicit reviews', async t => {
  const f = fixture(t); const alice = f.actor(); await issuer(f);
  Object.assign(f.env, { APP_ENV: 'production', OPERATOR_NAME: 'Example operator', TURNSTILE_SITE_KEY: 'site', TURNSTILE_SECRET_KEY: 'secret' });
  f.db.prepare('INSERT INTO operators VALUES(?,?)').run(alice.id, new Date().toISOString());
  f.db.prepare('INSERT INTO operator_security(user_id,enabled) VALUES(?,1)').run(alice.id);
  for (const kind of ['terms', 'privacy', 'safety']) {
    const body = 'Reviewed policy content for ' + kind;
    f.db.prepare('INSERT INTO site_policies VALUES(?,?,?,?)').run(kind, body, alice.id, new Date().toISOString());
    f.db.prepare('INSERT INTO policy_reviews VALUES(?,?,?,?)').run(kind, '1.0', await sha256(body), new Date().toISOString());
  }
  for (const name of ['turnstile', 'age_verifier', 'email_verification', 'storage']) await recordIntegration(f.c(), name, 'Test evidence');
  for (const name of ['audience_review', 'email_test', 'backup_restore', 'moderation', 'browser_test']) f.db.prepare('INSERT INTO launch_attestations VALUES(?,?,?,?,?)').run(name, alice.id, 'Test declaration only', f.env.PUBLIC_ORIGIN, new Date().toISOString());
  const ready = await launchReadiness(f.c()); assert.equal(ready.ready, true, JSON.stringify(ready.checks.filter(x => !x.ok)));
  f.db.prepare("UPDATE site_policies SET body='Changed without review' WHERE kind='terms'").run();
  assert.equal((await launchReadiness(f.c())).ready, false);
});

test('mail sender rotation preserves the original queued idempotent payload', async t => {
  const f = fixture(t), alice = f.actor(); const payloads = []; let count = 0;
  mockFetch(t, async (_url, opts) => { payloads.push(opts.body); return ++count === 1 ? new Response('', { status: 503 }) : Response.json({ id: 'sent' }); });
  await sendMail(f.c(), alice.email, 'Test', 'Private', { userId: alice.id });
  await processMail(f.c()); f.env.MAIL_FROM = 'Another <other@example.com>'; f.db.prepare('UPDATE mail_jobs SET next_attempt=0').run(); await processMail(f.c());
  assert.equal(payloads[0], payloads[1]); assert.equal(JSON.parse(payloads[1]).from, 'Synapse <test@example.com>');
});

test('removing a follower cannot remove another account relationship', async t => {
  const f = fixture(t), alice = f.actor(), bob = f.actor('bob'), clara = f.actor('clara');
  f.db.prepare('INSERT INTO follows VALUES(?,?)').run(bob.id, alice.id);
  f.db.prepare('INSERT INTO follows VALUES(?,?)').run(bob.id, clara.id);
  await route('DELETE /api/account/followers/:follower_id')(f.c({}, alice, 'DELETE', { follower_id: bob.id }));
  const follows = f.db.prepare('SELECT * FROM follows').all(); assert.equal(follows.length, 1); assert.equal(follows[0].target_id, clara.id);
});
