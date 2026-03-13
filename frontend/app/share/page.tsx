"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { uploadAudio } from "@/lib/api";

/**
 * Fallback share target page.
 *
 * The service worker normally intercepts POST /share and forwards
 * the file to the upload API. This page handles the edge case where
 * the SW isn't active yet (first install, or browser cleared SW).
 *
 * It reads the shared file from the request FormData, uploads it,
 * then redirects to the home page.
 */
export default function SharePage() {
  const router = useRouter();
  const [status, setStatus] = useState("Processing shared file...");

  useEffect(() => {
    // If we landed here via GET (SW wasn't ready), just redirect home
    router.replace("/");
  }, [router]);

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-4">
      <Loader2 className="w-8 h-8 text-vs-text-accent animate-spin" />
      <p className="text-sm text-vs-text-secondary">{status}</p>
    </div>
  );
}
