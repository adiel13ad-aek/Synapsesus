// Private local development aid. Never reads the remote database or sends mail.
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {decryptSecret} from '../src/core.js';
const root=resolve(fileURLToPath(new URL('..',import.meta.url)));
let vars={};try{for(const line of readFileSync(resolve(root,'.dev.vars'),'utf8').split(/\r?\n/)){const m=line.match(/^([A-Z_]+)=(.*)$/);if(m)vars[m[1]]=m[2];}}catch{throw Error('Configure primeiro .dev.vars com node scripts/setup.mjs --local-secrets.');}
if(vars.APP_ENV!=='development'||!/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(vars.PUBLIC_ORIGIN||''))throw Error('Este utilitário só aceita desenvolvimento local.');
const result=spawnSync(process.execPath,[resolve(root,'node_modules/wrangler/bin/wrangler.js'),'d1','execute','DB','--local','--json','--command',"SELECT encrypted_message FROM mail_jobs WHERE encrypted_message<>'' AND expires>unixepoch() ORDER BY created_at DESC LIMIT 10"],{cwd:root,encoding:'utf8',env:{...process.env,WRANGLER_SEND_METRICS:'false'}});
if(result.status!==0)throw Error('Não foi possível ler o banco LOCAL. Execute as migrations locais e inicie o app.');
let results;try{results=JSON.parse(result.stdout);}catch{throw Error('Resposta local inesperada. Nenhum conteúdo foi exibido.');}
console.log('SOMENTE TESTE LOCAL. Não houve entrega de e-mail. Não compartilhe estes links.');
let count=0;for(const group of results)for(const row of group.results||[]){const p=JSON.parse(await decryptSecret({env:vars},row.encrypted_message));console.log('\nPara: '+p.to+'\n'+p.subject+'\n'+p.text);count++;}
if(!count)console.log('Nenhuma mensagem local válida. Solicite um novo link no aplicativo.');
