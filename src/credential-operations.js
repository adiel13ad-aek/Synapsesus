import {fail, uid, stamp, first, run, batch} from './core.js';
import {newExternalCredential, createCredential, deleteExternal, isExternal} from './credentials.js';

export async function provisionCredential(c, address, password) {
  if (c.env.AUTH_PROVIDER !== 'supabase') return createCredential(c, address, password);
  const prepared = newExternalCredential(c);
  // Persist BEFORE network I/O: timeout or Worker termination cannot lose the
  // UUID needed to remove an uncommitted provider account. No passwords stored.
  await run(c, 'INSERT INTO credential_cleanup VALUES(?,?)', prepared, stamp() + 3600);
  return createCredential(c, address, password, prepared);
}

export function finishProvision(c, credential, id) {
  return isExternal(credential) ? [[
    'DELETE FROM credential_cleanup WHERE credential=? AND EXISTS(SELECT 1 FROM actors WHERE id=? AND password_hash=?)',
    credential, id, credential
  ]] : [];
}

export async function withCredentialLock(c, user, callback) {
  const owner = uid(), time = stamp();
  const acquired = await first(c, `INSERT INTO auth_operation_locks(user_id,owner,expires)
    SELECT ?,?,? WHERE EXISTS(SELECT 1 FROM actors WHERE id=? AND password_hash=? AND active=1)
    ON CONFLICT(user_id) DO UPDATE SET owner=excluded.owner,expires=excluded.expires
    WHERE auth_operation_locks.expires<? RETURNING owner`,
    user.id, owner, time + 300, user.id, user.password_hash, time);
  if (acquired?.owner !== owner) fail(409, 'A conta está sendo alterada. Aguarde e entre novamente.');
  try { return await callback(); }
  finally { await run(c, 'DELETE FROM auth_operation_locks WHERE user_id=? AND owner=?', user.id, owner); }
}

export async function processCredentialCleanup(c) {
  if (c.env.AUTH_PROVIDER !== 'supabase') return;
  const rows = await c.env.DB.prepare('SELECT credential FROM credential_cleanup WHERE not_before<=? LIMIT 10').bind(stamp()).all();
  for (const {credential} of rows.results || []) {
    if (!isExternal(credential)) continue;
    // Compare immutable identity, not the credential's revision nonce.
    const prefix = credential.split('$').slice(0, 3).join('$') + '$%';
    if (await first(c, 'SELECT id FROM actors WHERE password_hash LIKE ? LIMIT 1', prefix)) {
      await run(c, 'DELETE FROM credential_cleanup WHERE credential=?', credential);
      continue;
    }
    try {
      await deleteExternal(c, credential);
      await run(c, 'DELETE FROM credential_cleanup WHERE credential=?', credential);
    } catch {
      // Retain durable work on provider outages; never log credentials or keys.
      console.error('credential_cleanup_pending');
      await run(c, 'UPDATE credential_cleanup SET not_before=? WHERE credential=?', stamp() + 300, credential);
    }
  }
}
