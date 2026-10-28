'use strict';
const CACHE='synapse-ui-v10';
const ASSETS=['/','/index.html','/style.css','/base.css','/redesign.css','/visual-assets.js','/app.js','/features.js','/demo-adapter.js','/icon.svg','/icon-192.png','/icon-512.png','/manifest.webmanifest'];
self.addEventListener('install',event=>{event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)));self.skipWaiting();});
self.addEventListener('activate',event=>{event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('synapse-')&&k!==CACHE).map(k=>caches.delete(k)))));self.clients.claim();});
self.addEventListener('fetch',event=>{
 const url=new URL(event.request.url);
 // Never cache sessions, search results, messages, account data or uploaded media.
 if(event.request.method!=='GET'||url.origin!==self.location.origin||url.search||!ASSETS.includes(url.pathname))return;
 event.respondWith(fetch(event.request).then(response=>{if(response.ok){const copy=response.clone();caches.open(CACHE).then(cache=>cache.put(event.request,copy));}return response;}).catch(()=>caches.match(event.request)));
});

// Push payloads contain no private message text. A click can open only this origin.
self.addEventListener('push',event=>{
 let p={};try{p=event.data?.json()||{};}catch{}
 event.waitUntil(self.registration.showNotification('Synapse',{body:typeof p.body==='string'?p.body.slice(0,180):'Novas interações na sua conta.',icon:'/icon-192.png',badge:'/icon-192.png',tag:'synapse-activity',data:{url:'/?activity=1'}}));
});
self.addEventListener('notificationclick',event=>{
 event.notification.close();event.waitUntil(clients.matchAll({type:'window',includeUncontrolled:true}).then(async list=>{
   const url=new URL('/?activity=1',self.location.origin).href;
   for(const client of list)if(new URL(client.url).origin===self.location.origin){await client.navigate(url);return client.focus();}
   return clients.openWindow(url);
 }));
});
