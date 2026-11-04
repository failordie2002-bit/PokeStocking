/* PokéStock-owned service worker: notification display, no third-party SDK */
'use strict';
self.addEventListener('notificationclick',event=>{
  event.notification.close();
  event.waitUntil((async()=>{
    const tabs=await clients.matchAll({type:'window',includeUncontrolled:true});
    for(const t of tabs){if(t.url.includes(self.registration.scope) && 'focus' in t) return t.focus();}
    if(clients.openWindow) return clients.openWindow('./');
  })());
});
