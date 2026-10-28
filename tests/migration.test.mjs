import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
const root=resolve(fileURLToPath(new URL('..',import.meta.url)));
const py=process.env.PYTHON || 'python3';
const run=(args)=>spawnSync(py,args,{cwd:root,encoding:'utf8'});
async function fixture(){
 const dir=await mkdtemp(resolve(tmpdir(),'synapse-migrate-'));
 await mkdir(resolve(dir,'media'));
 const code=`import sqlite3,sys,pathlib\nc=sqlite3.connect(sys.argv[1]);c.executescript(pathlib.Path('migrations/0001_initial.sql').read_text());c.execute("INSERT INTO actors(id,handle,name,kind,password_hash,created_at,email,terms_version,age_band,age_verified_until) VALUES('u','usuario','Usuário','human','pbkdf2_sha256$600000$salt$hash','2026-10-28','user@example.test','old','adult',9999999999)");c.execute("INSERT INTO posts(id,author_id,body,source,created_at,image_path) VALUES('p','u','teste','human','2026-10-28','/media/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg')");c.execute("INSERT INTO sessions VALUES('session','u','csrf',9999999999)");c.commit()`;
 const created=run(['-c',code,resolve(dir,'old.db')]);assert.equal(created.status,0,created.stderr);
 await writeFile(resolve(dir,'media','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg'),Buffer.from([255,216,255,217]));
 return dir;
}
test('offline migration preserves social records and hash, invalidates sessions, preserves private bytes, leaves source untouched',async()=>{
 const dir=await fixture();try {
  const db=resolve(dir,'old.db');const before=createHash('sha256').update(await readFile(db)).digest('hex');
  const output=resolve(dir,'out');const result=run(['scripts/migrate.py','--database',db,'--media',resolve(dir,'media'),'--output',output,'--server-stopped']);
  assert.equal(result.status,0,result.stderr);
  assert.equal(createHash('sha256').update(await readFile(db)).digest('hex'),before);
  const manifest=JSON.parse(await readFile(resolve(output,'manifest.json'),'utf8'));
  assert.equal(manifest.counts.actors,1);assert.equal(manifest.counts.posts,1);assert.equal(manifest.discarded_ephemeral_records.sessions,1);assert.equal(manifest.media.length,1);
  const inspect=run(['-c',`import sqlite3,pathlib,sys,json\nc=sqlite3.connect(':memory:');c.executescript(pathlib.Path('migrations/0001_initial.sql').read_text());c.executescript(pathlib.Path(sys.argv[1]).read_text());print(json.dumps({'hash':c.execute('SELECT password_hash FROM actors').fetchone()[0],'sessions':c.execute('SELECT count(*) FROM sessions').fetchone()[0],'age':c.execute('SELECT age_band FROM actors').fetchone()[0],'maintenance':c.execute('SELECT maintenance FROM site_settings').fetchone()[0]}))`,resolve(output,'import.sql')]);
  assert.equal(inspect.status,0,inspect.stderr);
  assert.deepEqual(JSON.parse(inspect.stdout),{hash:'pbkdf2_sha256$600000$salt$hash',sessions:0,age:'unknown',maintenance:1});
 }finally{await rm(dir,{recursive:true,force:true});}
});
test('migration refuses live-server declaration absence and missing referenced media without leaving an export',async()=>{
 const dir=await fixture();try {
  const output=resolve(dir,'out');
  let result=run(['scripts/migrate.py','--database',resolve(dir,'old.db'),'--media',resolve(dir,'media'),'--output',output]);
  assert.notEqual(result.status,0);
  await rm(resolve(dir,'media','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg'));
  result=run(['scripts/migrate.py','--database',resolve(dir,'old.db'),'--media',resolve(dir,'media'),'--output',output,'--server-stopped']);
  assert.notEqual(result.status,0);assert.match(result.stderr,/ausente/);
  await assert.rejects(readFile(resolve(output,'import.sql')));
 }finally{await rm(dir,{recursive:true,force:true});}
});
test('migration import refuses a nonempty destination before changing records',async()=>{
 const dir=await fixture();try {
  const output=resolve(dir,'out');const result=run(['scripts/migrate.py','--database',resolve(dir,'old.db'),'--media',resolve(dir,'media'),'--output',output,'--server-stopped']);
  assert.equal(result.status,0,result.stderr);
  const check=run(['-c',`import sqlite3,pathlib,sys\nc=sqlite3.connect(':memory:');c.executescript(pathlib.Path('migrations/0001_initial.sql').read_text());c.execute("INSERT INTO actors(id,handle,name,kind,created_at) VALUES('existing','existing','Existing','human','2026')");c.commit()\ntry:c.executescript(pathlib.Path(sys.argv[1]).read_text());raise Exception('import should fail')\nexcept sqlite3.IntegrityError:assert c.execute('SELECT id FROM actors').fetchone()[0]=='existing';print('ok')`,resolve(output,'import.sql')]);
  assert.equal(check.status,0,check.stderr);assert.equal(check.stdout.trim(),'ok');
 }finally{await rm(dir,{recursive:true,force:true});}
});
