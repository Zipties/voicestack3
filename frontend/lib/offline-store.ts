const DB_NAME = "voicestack-offline";
const DB_VERSION = 1;
const STORE_NAME = "pending-uploads";

export interface PendingRecording {
  id: string;
  blob: Blob;
  filename: string;
  mimeType: string;
  createdAt: number;
  /** Number of upload attempts so far */
  attempts: number;
}

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "id" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function savePending(recording: PendingRecording): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).put(recording);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function removePending(id: string): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function getAllPending(): Promise<PendingRecording[]> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const req = tx.objectStore(STORE_NAME).getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function getPendingCount(): Promise<number> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const req = tx.objectStore(STORE_NAME).count();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/** Try to upload all pending recordings. Returns number of successful uploads. */
export async function flushPending(
  uploadFn: (file: File) => Promise<{ job_id: string }>,
  onUploaded?: (id: string, jobId: string) => void,
): Promise<number> {
  const pending = await getAllPending();
  let uploaded = 0;

  for (const rec of pending) {
    try {
      const file = new File([rec.blob], rec.filename, { type: rec.mimeType });
      const result = await uploadFn(file);
      await removePending(rec.id);
      onUploaded?.(rec.id, result.job_id);
      uploaded++;
    } catch {
      // Update attempt count but keep in store for next try
      await savePending({ ...rec, attempts: rec.attempts + 1 });
    }
  }

  return uploaded;
}
