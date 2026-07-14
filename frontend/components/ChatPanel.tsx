"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { AgentAction, Timeline } from "@/lib/types";

interface Message {
  role: "user" | "agent" | "error";
  text: string;
  actions?: AgentAction[];
}

const SUGGESTIONS = [
  "Add the first video to the timeline",
  "Trim the first clip to the first 5 seconds",
  "Add a title saying “My Vacation” to the first clip",
  "Speed up the last clip 2x and mute it",
  "Export the video",
];

export default function ChatPanel({
  projectId,
  onTimelineChanged,
}: {
  projectId: string;
  onTimelineChanged: (t: Timeline) => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send(text?: string) {
    const message = (text ?? input).trim();
    if (!message || busy) return;
    setInput("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", text: message }]);
    try {
      const res = await api.sendAgentMessage(projectId, message);
      setMessages((m) => [...m, { role: "agent", text: res.reply, actions: res.actions }]);
      onTimelineChanged(res.timeline);
    } catch (e) {
      setMessages((m) => [...m, { role: "error", text: (e as Error).message }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <span className="overline" style={{ marginBottom: 12 }}>Correspondence</span>

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="muted" style={{ fontSize: 13 }}>
            Tell the agent what to do, e.g.:
            <ul style={{ paddingLeft: 18, marginTop: 6 }}>
              {SUGGESTIONS.map((s) => (
                <li key={s} style={{ cursor: "pointer", marginBottom: 4 }} onClick={() => send(s)}>
                  {s}
                </li>
              ))}
            </ul>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.text}
            {m.actions && m.actions.length > 0 && (
              <div className="actions">
                {m.actions.map((a, j) => (
                  <div key={j}>▸ {a.tool}</div>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="msg agent muted">Working…</div>}
        <div ref={bottomRef} />
      </div>

      <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
        <textarea
          rows={2}
          style={{ flex: 1, resize: "none" }}
          placeholder="e.g. cut the first 10 seconds and add a title"
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button className="primary" onClick={() => send()} disabled={busy || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
