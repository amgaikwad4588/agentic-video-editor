"use client";

// The Konva overlay layer touches `canvas` at import time, which crashes
// during SSR - so the actual player is loaded client-side only.
import dynamic from "next/dynamic";

const PreviewPlayerInner = dynamic(() => import("./PreviewPlayerInner"), {
  ssr: false,
  loading: () => <div className="muted" style={{ padding: 20 }}>Loading preview…</div>,
});

export default PreviewPlayerInner;
