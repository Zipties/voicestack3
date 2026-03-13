const CACHE_NAME = "voicestack-v3";
const OFFLINE_DB = "voicestack-offline";
const OFFLINE_STORE = "pending-uploads";

// Static assets to precache
const PRECACHE_URLS = ["/", "/speakers", "/settings"];

// Install: precache shell
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// Fetch: share target handler + network-first for assets
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Handle share target POST
  if (url.pathname === "/share" && event.request.method === "POST") {
    event.respondWith(
      (async () => {
        const formData = await event.request.formData();
        const file = formData.get("file");

        if (file) {
          // Forward to upload API
          const uploadForm = new FormData();
          uploadForm.append("file", file);

          try {
            const res = await fetch("/api/jobs/", {
              method: "POST",
              body: uploadForm,
            });

            if (res.ok) {
              // Redirect to home page to see the new job
              return Response.redirect("/", 303);
            }
          } catch (e) {
            console.error("[sw] Share upload failed:", e);
          }
        }

        // Fallback: redirect to home even on failure
        return Response.redirect("/", 303);
      })()
    );
    return;
  }

  // Skip other non-GET requests
  if (event.request.method !== "GET") return;

  // Skip API requests, SSE, audio streaming - always network
  if (
    url.pathname.startsWith("/api/") ||
    url.pathname.includes("/progress") ||
    url.pathname.includes("/audio/")
  ) {
    return;
  }

  // For navigation and static assets: network-first with cache fallback
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Cache successful responses
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

// ─── Background Sync: upload pending recordings when connectivity returns ────

function openOfflineDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(OFFLINE_DB, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(OFFLINE_STORE)) {
        db.createObjectStore(OFFLINE_STORE, { keyPath: "id" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function getAllPendingSW(db) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(OFFLINE_STORE, "readonly");
    const req = tx.objectStore(OFFLINE_STORE).getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function removePendingSW(db, id) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(OFFLINE_STORE, "readwrite");
    tx.objectStore(OFFLINE_STORE).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

self.addEventListener("sync", (event) => {
  if (event.tag === "upload-pending") {
    event.waitUntil(uploadAllPending());
  }
});

async function uploadAllPending() {
  let db;
  try {
    db = await openOfflineDB();
  } catch {
    return; // IndexedDB unavailable in SW context
  }

  const pending = await getAllPendingSW(db);
  for (const rec of pending) {
    const form = new FormData();
    form.append("file", new File([rec.blob], rec.filename, { type: rec.mimeType }));

    try {
      const res = await fetch("/api/jobs/", { method: "POST", body: form });
      if (res.ok) {
        await removePendingSW(db, rec.id);
      }
    } catch {
      // Still offline - sync manager will retry later
      throw new Error("Upload failed, will retry");
    }
  }
}
