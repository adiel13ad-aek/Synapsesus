"use strict";
(async function(){
 const slot=document.getElementById('operator-info');if(!slot)return;
 try{
  const r=await fetch('/api/public-info',{credentials:'same-origin'});if(!r.ok)throw new Error('contact');
  const p=await r.json();slot.replaceChildren();
  const add=(label,value)=>{const line=document.createElement('span');line.textContent=label+value;slot.append(line,document.createElement('br'));};
  add('Operador: ',p.operator||'não informado');
  add('Suporte: ',p.support_email||'não configurado');
  add('Segurança infantil: ',p.child_safety_email||'não configurado');
  add('Ambiente: ',p.production?'produção — configuração não equivale a certificação':'teste privado');
 }catch(e){slot.textContent='Contato indisponível neste momento. Este pacote não fornece uma equipe de suporte.';}
})();
