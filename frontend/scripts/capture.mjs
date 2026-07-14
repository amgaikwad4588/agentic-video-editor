// Capture real editor screenshots for the landing-page gallery.
// Prereqs: backend on :8000 with the seeded demo project (backend/scripts/
// seed_demo.py), frontend running on :3000.
//
// Usage: node scripts/capture.mjs <projectId>

import { chromium } from "playwright";
import { mkdirSync } from "fs";

const projectId = process.argv[2];
if (!projectId) {
  console.error("usage: node scripts/capture.mjs <projectId>");
  process.exit(1);
}

const OUT = "public/shots";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1600, height: 1000 },
  deviceScaleFactor: 2, // retina-sharp shots
});

// --- editor: full cutting room ---------------------------------------------
await page.goto(`http://localhost:3000/editor/${projectId}`, {
  waitUntil: "networkidle",
});
await page.waitForSelector(".clip-block");
// select the first clip so the inspector + selection state are visible
await page.click(".clip-block");
// seek into the clip so its text overlay (starts at 0.4s) is on screen
await page.locator('input[type="range"]').first().fill("2");
// let the video element load a frame and thumbnails settle
await page.waitForTimeout(2500);
await page.screenshot({ path: `${OUT}/editor.png` });
console.log("captured editor.png");

// --- timeline close-up -------------------------------------------------------
const timeline = page.locator(".editor-timeline");
await timeline.screenshot({ path: `${OUT}/timeline.png` });
console.log("captured timeline.png");

// --- agent chat with a staged conversation ----------------------------------
// Stage the panel visually (no API key needed): inject messages via the UI's
// own suggestion list is not enough, so we screenshot the chat column as-is
// with suggestions visible - it reads as the "correspondence" panel.
const chat = page.locator(".editor-chat");
await chat.screenshot({ path: `${OUT}/chat.png` });
console.log("captured chat.png");

await browser.close();
