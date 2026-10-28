#!/usr/bin/env node
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomBytes } from 'node:crypto';
import { createInterface } from 'node:readline/promises';
import { stdin, stdout } from 'node:process';

const root=resolve(fileURLToPath(new URL('..',import.meta.url)));
const flags=new Set(process.argv.slice(2));
const key=()=>randomBytes(32).toString('base64url');
const local=flags.has('--local-secrets');
if(local) {
  const output=resolve(root,'.dev.vars');
  await writeFile(output,`# Somente desenvolvimento local\nAPP_ENV=development\nPUBLIC_ORIGIN=http://localhost:8787\nAGE_ENFORCED=0\nSETUP_TOKEN=${key()}\nADMIN_ENCRYPTION_KEY=${key()}\n`,{flag:'wx',mode:0o600});
  console.log('.dev.vars criado; valores privados não foram exibidos.');
  process.exit(0);
}
if(flags.has('--secrets')) {
  const privateDir=resolve(root,'.private');
  await mkdir(privateDir,{recursive:true,mode:0o700});
  const output=resolve(privateDir,'first-install-secrets.json');
  await writeFile(output,JSON.stringify({SETUP_TOKEN:key(),ADMIN_ENCRYPTION_KEY:key()},null,2)+'\n',{flag:'wx',mode:0o600});
  console.log('Segredos exclusivos da PRIMEIRA instalação criados em .private/first-install-secrets.json.');
  console.log('Importe com npx wrangler secret bulk .private/first-install-secrets.json. Não substitua a chave de uma instalação existente.');
  process.exit(0);
}
const cli=createInterface({input:stdin,output:stdout});
async function ask(label,valid) {
  for(;;) {
    const answer=(await cli.question(label+': ')).trim();
    if(valid(answer)) return answer;
    console.log('Valor inválido; confira e tente novamente.');
  }
}
try {
  console.log('Configura somente nomes públicos e IDs locais. Não cria recursos nem faz implantação.');
  const config=JSON.parse(await readFile(resolve(root,'wrangler.jsonc'),'utf8'));
  config.name=await ask('Nome do Worker (igual ao painel Cloudflare)',v=>/^[a-z0-9][a-z0-9-]{0,61}$/.test(v));
  config.d1_databases[0].database_name=await ask('Nome do banco D1',v=>/^[a-zA-Z0-9_-]{1,63}$/.test(v));
  config.d1_databases[0].database_id=await ask('UUID real do D1',v=>/^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i.test(v)&&!/^0{8}-/.test(v));
  config.r2_buckets[0].bucket_name=await ask('Nome do bucket R2 PRIVADO',v=>/^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$/.test(v));
  config.vars.PUBLIC_ORIGIN=await ask('Origem HTTPS final (ex.: https://synapse-discovery.sua-conta.workers.dev)',v=>{
    try { const u=new URL(v);return u.protocol==='https:'&&u.pathname==='/'&&!u.search&&!u.hash&&!u.username&&!u.password&&!u.hostname.endsWith('.invalid');} catch{return false;}
  });
  config.vars.PUBLIC_ORIGIN=config.vars.PUBLIC_ORIGIN.replace(/\/$/,'');
  config.vars.APP_ENV='production';config.vars.AGE_ENFORCED='1';
  await writeFile(resolve(root,'wrangler.jsonc'),JSON.stringify(config,null,2)+'\n');
  console.log('wrangler.jsonc atualizado. IDs, nomes de recursos e origem são públicos e podem ir ao GitHub.');
  console.log('Nenhum recurso remoto foi criado. Configure os secrets e contatos antes da abertura.');
} finally { cli.close(); }
