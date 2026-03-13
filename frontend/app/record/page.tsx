"use client";

import { useRouter } from "next/navigation";
import { Recorder } from "@/components/recorder";

export default function RecordPage() {
  const router = useRouter();

  return (
    <Recorder
      onRecordingComplete={(jobId) => {
        router.push(`/jobs/${jobId}`);
      }}
      onClose={() => {
        router.back();
      }}
    />
  );
}
