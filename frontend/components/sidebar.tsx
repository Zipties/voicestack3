"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import { AudioWaveform, Mic, Users, Settings, Plus, Menu, X, Upload } from "lucide-react";
import { PendingUploads } from "@/components/pending-uploads";

const NAV_ITEMS = [
  { href: "/", label: "Recordings", icon: Mic },
  { href: "/speakers", label: "Speakers", icon: Users },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  // Close sidebar on route change (mobile)
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // Close on escape key
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    if (open) {
      document.addEventListener("keydown", handleKey);
      return () => document.removeEventListener("keydown", handleKey);
    }
  }, [open]);

  const sidebarContent = (
    <>
      {/* Logo */}
      <div className="p-5 flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-lg bg-vs-text-accent/15 flex items-center justify-center">
          <AudioWaveform className="w-4.5 h-4.5 text-vs-text-accent" />
        </div>
        <span className="font-semibold text-vs-text-primary tracking-tight">
          VoiceStack
        </span>
        {/* Close button - mobile only */}
        <button
          onClick={() => setOpen(false)}
          className="ml-auto md:hidden p-1 rounded-lg text-vs-text-secondary hover:text-vs-text-primary hover:bg-vs-hover"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Action buttons */}
      <div className="px-3 mb-2 space-y-1.5">
        <Link
          href="/record"
          className="btn-primary w-full flex items-center justify-center gap-2 text-sm"
        >
          <Mic className="w-4 h-4" />
          Record
        </Link>
        <Link
          href="/?upload=true"
          className="btn-ghost w-full flex items-center justify-center gap-2 text-sm border border-vs-border"
        >
          <Upload className="w-4 h-4" />
          Upload File
        </Link>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-2 space-y-0.5">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active =
            href === "/"
              ? pathname === "/" || pathname.startsWith("/jobs")
              : pathname.startsWith(href);

          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors duration-100 ${
                active
                  ? "bg-vs-hover text-vs-text-primary font-medium"
                  : "text-vs-text-secondary hover:bg-vs-hover hover:text-vs-text-primary"
              }`}
            >
              <Icon className="w-4 h-4" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Pending uploads indicator */}
      <div className="px-2 mb-1">
        <PendingUploads />
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-vs-border">
        <p className="text-2xs text-vs-text-muted">
          VoiceStack3 v0.1.0
        </p>
      </div>
    </>
  );

  return (
    <>
      {/* Hamburger button - mobile only */}
      <button
        onClick={() => setOpen(true)}
        className="md:hidden fixed top-3 left-3 z-50 p-2 rounded-lg bg-vs-surface border border-vs-border text-vs-text-secondary hover:text-vs-text-primary hover:bg-vs-hover"
        aria-label="Open menu"
      >
        <Menu className="w-5 h-5" />
      </button>

      {/* Desktop sidebar - always visible */}
      <aside className="hidden md:flex w-56 shrink-0 bg-vs-surface border-r border-vs-border flex-col">
        {sidebarContent}
      </aside>

      {/* Mobile overlay */}
      {open && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
          onClick={() => setOpen(false)}
        />
      )}

      {/* Mobile slide-out sidebar */}
      <aside
        className={`md:hidden fixed top-0 left-0 z-50 h-full w-64 bg-vs-surface border-r border-vs-border flex flex-col transition-transform duration-200 ease-out ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {sidebarContent}
      </aside>
    </>
  );
}
