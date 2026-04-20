/**
 * CommPlexEdge/pwa/sw.js — Arc Badlands CommPlex Service Worker
 * Domain: CommPlexEdge (The Hands)
 *
 * Handles:
 *   - Push notifications from CommPlexAPI (qualified leads, alerts)
 *   - Offline cache of dashboard shell (stale-while-revalidate)
 *   - Background sync for lead status updates
 *
 * Install:
 *   Registered in index.html via navigator.serviceWorker.register('/pwa/sw.js')
 *
 * Push Payload format (from CommPlexAPI notifier):
 *   {
 *     "title":    "🚨 QUALIFIED DEAL — MKZ",
 *     "body":     "Dealer: Fargo Ford\nOffer: $25,000",
 *     "category": "qualified",
 *     "url":      "https://your-gateway/leads/42",
 *     "lead_id":  42
 *   }
 */

'use strict';

const CACHE_NAME    = 'commplex-v1';
const CACHE_VERSION = '1.0.0';

// ── Shell assets to cache for offline use ─────────────────────────────────────
const SHELL_ASSETS = [
  '/',
  '/index.html',
  '/pwa/manifest.json',
  '/css/dashboard.css',
  '/js/dashboard.js',
  '/icons/icon-192x192.png',
  '/icons/icon-512x512.png',
];

// ── Notification categories ───────────────────────────────────────────────────
const NOTIFICATION_ICONS = {
  qualified: '/icons/icon-192x192.png',
  alert:     '/icons/icon-192x192.png',
  standup:   '/icons/icon-192x192.png',
  default:   '/icons/icon-192x192.png',
};

const VIBRATION_PATTERNS = {
  qualified: [200, 100, 200, 100, 400],  // urgent double-tap
  alert:     [300, 100, 300],            // alert pattern
  standup:   [200, 100, 200],            // gentle reminder
  default:   [200],
};


// ═══════════════════════════════════════════════════════
// INSTALL — Cache shell assets
// ═══════════════════════════════════════════════════════

self.addEventListener('install', (event) => {
  console.log(`[CommPlexSW] Installing v${CACHE_VERSION}`);
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[CommPlexSW] Caching shell assets');
      // addAll fails if any asset 404s — use individual add() for resilience
      return Promise.allSettled(
        SHELL_ASSETS.map(url => cache.add(url).catch(e =>
          console.warn(`[CommPlexSW] Failed to cache ${url}: ${e.message}`)
        ))
      );
    }).then(() => self.skipWaiting())
  );
});


// ═══════════════════════════════════════════════════════
// ACTIVATE — Clean old caches, take control
// ═══════════════════════════════════════════════════════

self.addEventListener('activate', (event) => {
  console.log('[CommPlexSW] Activating');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter(name => name !== CACHE_NAME)
          .map(name => {
            console.log(`[CommPlexSW] Deleting old cache: ${name}`);
            return caches.delete(name);
          })
      );
    }).then(() => self.clients.claim())
  );
});


// ═══════════════════════════════════════════════════════
// FETCH — Stale-While-Revalidate for dashboard shell
// Network-first for API calls
// ═══════════════════════════════════════════════════════

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Skip non-GET and cross-origin requests
  if (event.request.method !== 'GET') return;
  if (url.origin !== location.origin) return;

  // API calls — network first, no cache
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/webhook/')) {
    event.respondWith(fetch(event.request));
    return;
  }

  // Shell assets — stale-while-revalidate
  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      const cached = await cache.match(event.request);
      const fetchPromise = fetch(event.request).then((response) => {
        if (response && response.status === 200) {
          cache.put(event.request, response.clone());
        }
        return response;
      }).catch(() => cached); // offline fallback to cache

      return cached || fetchPromise;
    })
  );
});


// ═══════════════════════════════════════════════════════
// PUSH — Receive CommPlexAPI notifications
// ═══════════════════════════════════════════════════════

self.addEventListener('push', (event) => {
  console.log('[CommPlexSW] Push received');

  let payload = {
    title:    'Arc Badlands CommPlex',
    body:     'New update available',
    category: 'default',
    url:      '/',
    lead_id:  null,
  };

  if (event.data) {
    try {
      payload = { ...payload, ...event.data.json() };
    } catch (e) {
      payload.body = event.data.text();
    }
  }

  const category = payload.category || 'default';
  const options  = {
    body:    payload.body,
    icon:    NOTIFICATION_ICONS[category] || NOTIFICATION_ICONS.default,
    badge:   '/icons/icon-96x96.png',
    vibrate: VIBRATION_PATTERNS[category] || VIBRATION_PATTERNS.default,
    tag:     `commplex-${category}-${payload.lead_id || Date.now()}`,
    renotify: true,
    requireInteraction: category === 'qualified',  // Stay on screen for leads
    data: {
      url:     payload.url || '/',
      lead_id: payload.lead_id,
      category,
    },
    actions: category === 'qualified'
      ? [
          { action: 'view',    title: '👁 View Lead' },
          { action: 'call',    title: '📞 Call Now'  },
          { action: 'dismiss', title: '✕ Dismiss'    },
        ]
      : [
          { action: 'view',    title: 'Open CommPlex' },
          { action: 'dismiss', title: 'Dismiss'        },
        ],
  };

  event.waitUntil(
    self.registration.showNotification(payload.title, options)
  );
});


// ═══════════════════════════════════════════════════════
// NOTIFICATION CLICK — Open lead or take action
// ═══════════════════════════════════════════════════════

self.addEventListener('notificationclick', (event) => {
  const { action, notification } = event;
  const data = notification.data || {};

  console.log(`[CommPlexSW] Notification click: action=${action} lead_id=${data.lead_id}`);
  notification.close();

  if (action === 'dismiss') return;

  let targetUrl = data.url || '/';

  if (action === 'call' && data.lead_id) {
    // Open the leads page filtered to this lead
    targetUrl = `/?view=leads&id=${data.lead_id}&action=call`;
  } else if (action === 'view' || !action) {
    targetUrl = data.lead_id
      ? `/?view=leads&id=${data.lead_id}`
      : (data.url || '/');
  }

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      // Focus existing CommPlex window if open
      for (const client of windowClients) {
        if (new URL(client.url).origin === location.origin && 'focus' in client) {
          client.postMessage({ type: 'NAVIGATE', url: targetUrl });
          return client.focus();
        }
      }
      // Open new window
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});


// ═══════════════════════════════════════════════════════
// NOTIFICATION CLOSE — Log dismissal
// ═══════════════════════════════════════════════════════

self.addEventListener('notificationclose', (event) => {
  const data = event.notification.data || {};
  console.log(`[CommPlexSW] Notification dismissed: lead_id=${data.lead_id}`);
});


// ═══════════════════════════════════════════════════════
// BACKGROUND SYNC — Lead status updates while offline
// ═══════════════════════════════════════════════════════

self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-lead-status') {
    console.log('[CommPlexSW] Background sync: lead status');
    event.waitUntil(syncPendingLeadUpdates());
  }
});

async function syncPendingLeadUpdates() {
  // Reads pending updates from IndexedDB and POSTs them to CommPlexAPI
  // Stubbed — wire to IndexedDB in CommPlexEdge/js/db.js
  console.log('[CommPlexSW] syncPendingLeadUpdates — stub (wire IndexedDB)');
}


// ═══════════════════════════════════════════════════════
// MESSAGE — Communication from main thread
// ═══════════════════════════════════════════════════════

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  if (event.data?.type === 'PING') {
    event.ports[0]?.postMessage({ type: 'PONG', version: CACHE_VERSION });
  }
});
