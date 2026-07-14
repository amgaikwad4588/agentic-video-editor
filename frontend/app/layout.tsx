import type { Metadata } from "next";
import { Inter, Playfair_Display } from "next/font/google";
import "./globals.css";

// Luxury/Editorial type pairing: high-contrast serif for display,
// humanist sans for UI. Loaded via next/font for zero layout shift.
const playfair = Playfair_Display({
  subsets: ["latin"],
  style: ["normal", "italic"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-display",
});

const inter = Inter({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: "Atelier — Agentic Video Editor",
  description: "Edit video with natural language",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${playfair.variable} ${inter.variable}`}>
        {/* Paper-grain overlay: tactile "expensive paper" texture at 2% */}
        <div className="noise-overlay" aria-hidden="true" />
        {/* Architectural gridlines aligned to the editorial grid (desktop) */}
        <div className="gridlines" aria-hidden="true">
          <span /><span /><span /><span />
        </div>
        {children}
      </body>
    </html>
  );
}
