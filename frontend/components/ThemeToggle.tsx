"use client";

import { useEffect, useState } from "react";

// The saved theme is applied to <html> pre-paint by an inline script in
// layout.tsx; this component only reflects and flips that state.
export default function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  }, []);

  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* private mode: theme just won't persist */
    }
    setTheme(next);
  }

  return (
    <button
      className="theme-toggle"
      onClick={toggle}
      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
    >
      {theme === "dark" ? "☀ Light" : "☽ Dark"}
    </button>
  );
}
