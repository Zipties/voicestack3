import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { ServiceWorker } from "@/components/service-worker";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: "#0c0e14",
};

export const metadata: Metadata = {
  title: "VoiceStack",
  description: "Audio intelligence: transcription, speaker ID, emotion detection",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "VoiceStack",
  },
  icons: {
    icon: "/icons/icon-192.png",
    apple: "/icons/apple-touch-icon.png",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="flex h-dvh overflow-hidden">
        <Sidebar />
        <main className="flex-1 min-h-0 overflow-hidden flex flex-col">{children}</main>
        <ServiceWorker />
      </body>
    </html>
  );
}
