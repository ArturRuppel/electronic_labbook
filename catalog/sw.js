// Service worker for the Lab Notebook PWA.
//
// Its only job is to make the app *installable* as a standalone desktop app —
// browsers require a registered service worker with a fetch handler before they
// offer the install prompt / open in an app window.
//
// We deliberately do NOT cache: this is a local, always-online admin tool served
// from localhost, so a cache would only risk showing stale pages after an edit
// or a regenerate. The fetch handler is a transparent network passthrough.

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => { /* default network fetch; nothing cached */ });
