import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Base surfaces
        vs: {
          bg: "#0c0e14",
          surface: "#13151e",
          raised: "#1a1d2a",
          hover: "#222538",
          border: "#2a2d3e",
          "border-bright": "#3a3d52",
        },
        // Text
        "vs-text": {
          primary: "#e8eaed",
          secondary: "#9ba1b0",
          muted: "#636879",
          accent: "#7c8dff",
        },
        // Speaker palette
        speaker: {
          0: "#ff6b9d",
          1: "#51a3ff",
          2: "#4ecdc4",
          3: "#ffb347",
          4: "#95e86c",
          5: "#c17bf5",
          6: "#ff6b6b",
          7: "#45d0e8",
        },
        // Emotion colors
        emotion: {
          happy: "#4ecdc4",
          sad: "#51a3ff",
          angry: "#ff6b6b",
          neutral: "#9ca3af",
          fearful: "#ffb347",
          surprised: "#c17bf5",
          disgusted: "#8b5e3c",
          other: "#6b7280",
          unknown: "#4b5563",
        },
        // Status colors
        status: {
          queued: "#eab308",
          processing: "#3b82f6",
          completed: "#22c55e",
          failed: "#ef4444",
        },
      },
      fontFamily: {
        sans: ['"DM Sans"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', '"Fira Code"', "monospace"],
      },
      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "0.875rem" }],
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fadeIn 0.2s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
