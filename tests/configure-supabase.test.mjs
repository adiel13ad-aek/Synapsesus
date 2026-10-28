import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, readFileSync, writeFileSync, rmSync, readdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {configureSupabase, mergeSupabaseConfig, supabaseSettings} from '../scripts/configure-supabase.mjs';

test('Supabase updater preserves deployed resources, custom origin and unrelated settings', () => {
  const original = {
    name:'custom-live-worker',
    d1_databases:[{binding:'DB',database_name:'live-db',database_id:'12345678-1234-1234-1234-123456789abc'}],
    r2_buckets:[{binding:'MEDIA',bucket_name:'live-private-bucket'}],
    vars:{PUBLIC_ORIGIN:'https://community.example.com',AGE_ENFORCED:'1',MAIL_FROM:'sender@example.com',CUSTOM_VALUE:'preserved'},
    env:{preview:{name:'different-preview',vars:{CUSTOM_VALUE:'preview'}}},
    limits:{cpu_ms:30000,subrequests:50},
    triggers:{crons:['*/5 * * * *']}
  };
  const before = structuredClone(original);
  const next = mergeSupabaseConfig(original);
  assert.deepEqual(original, before);
  assert.equal(next.name, original.name);
  for (const key of ['d1_databases','r2_buckets','env','triggers']) assert.deepEqual(next[key],original[key]);
  assert.deepEqual(next.vars, {...original.vars,...supabaseSettings});
  assert.deepEqual(next.limits,{subrequests:50});
  assert.ok(!('SUPABASE_SECRET_KEY' in next.vars));
});

test('updater replaces only known release placeholders and never adds a CPU limit', () => {
  const next=mergeSupabaseConfig({name:'synapse-discovery',vars:{PUBLIC_ORIGIN:'https://configure.invalid'}});
  assert.equal(next.name,'synapsesus');
  assert.equal(next.vars.PUBLIC_ORIGIN,'https://synapsesus.adielrodriguesdemorais793.workers.dev');
  assert.ok(!('limits' in next));
  assert.deepEqual(mergeSupabaseConfig(next), next);
});

test('updater backs up original bytes and is idempotent', t => {
  const dir=mkdtempSync(join(tmpdir(),'synapse-config-'));
  t.after(()=>rmSync(dir,{recursive:true,force:true}));
  const path=join(dir,'wrangler.jsonc'), original='{ "name": "synapsesus", "vars": {} }\n';
  writeFileSync(path,original);
  const result=configureSupabase(path);
  assert.equal(readFileSync(result.backup,'utf8'), original);
  assert.equal(JSON.parse(readFileSync(path,'utf8')).vars.AUTH_PROVIDER,'supabase');
  assert.equal(configureSupabase(path).changed,false);
  assert.equal(readdirSync(dir).length,2);
});

test('invalid or commented JSON is left untouched without a backup', t => {
  const dir=mkdtempSync(join(tmpdir(),'synapse-config-invalid-'));
  t.after(()=>rmSync(dir,{recursive:true,force:true}));
  const path=join(dir,'wrangler.jsonc'), original='{// comentário\n "name":"synapsesus"}';
  writeFileSync(path,original);
  assert.throws(()=>configureSupabase(path),/Não alterei o arquivo/);
  assert.equal(readFileSync(path,'utf8'),original);
  assert.equal(readdirSync(dir).length,1);
});
