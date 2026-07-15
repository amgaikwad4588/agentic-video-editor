"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { AgentAction, ChatTurn, Timeline } from "@/lib/types";

interface Message {
  role: "user" | "agent" | "error";
  text: string;
  actions?: AgentAction[];
  options?: string[];
}

const SUGGESTIONS = [
  "Add the first video to the timeline",
  "Trim the first clip to the first 5 seconds",
  "Add a title saying “My Vacation” to the first clip",
  "Split the first clip at 10 seconds",
  "Make the last clip black and white",
  "Add a 1 second fade out at the end",
  "Export the video",
];

// Recent turns replayed to the backend so follow-ups (answers to the agent's
// questions, "the second one") keep their context.
const HISTORY_LIMIT = 20;

function toHistory(messages: Message[]): ChatTurn[] {
  return messages
    .filter((m) => m.role !== "error")
    .slice(-HISTORY_LIMIT)
    .map((m) => ({ role: m.role as "user" | "agent", text: m.text }));
}

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
    const history = toHistory(messages);
    setMessages((m) => [...m, { role: "user", text: message }]);
    try {
      const res = await api.sendAgentMessage(projectId, message, history);
      setMessages((m) => [
        ...m,
        { role: "agent", text: res.reply, actions: res.actions, options: res.options },
      ]);
      onTimelineChanged(res.timeline);
    } catch (e) {
      setMessages((m) => [...m, { role: "error", text: (e as Error).message }]);
    } finally {
      setBusy(false);
    }
  }

  const lastIndex = messages.length - 1;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div style={{ marginBottom: 12 }}>
        <span className="overline">Correspondence</span>
        <div className="chat-status">
          <span className="dot" aria-hidden="true" />
          <span>{busy ? "The AI editor is working" : "Your AI editor, ready for direction"}</span>
        </div>
      </div>

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="muted" style={{ fontSize: 14 }}>
            Tell the agent what to do, e.g.:
            <ul style={{ paddingLeft: 18, marginTop: 6 }}>
              {SUGGESTIONS.map((s) => (
                <li key={s} className="suggestion" style={{ marginBottom: 6 }} onClick={() => send(s)}>
                  {s}
                </li>
              ))}
            </ul>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <span className="msg-role">
              {m.role === "user" ? "You" : m.role === "agent" ? "AI editor" : "Notice"}
            </span>
            {m.text}
            {m.actions && m.actions.length > 0 && (
              <div className="actions">
                {m.actions.map((a, j) => (
                  <div key={j}>&#9656; {a.tool}</div>
                ))}
              </div>
            )}
            {m.options && m.options.length > 0 && i === lastIndex && !busy && (
              <div className="chat-options">
                {m.options.map((option) => (
                  <button key={option} onClick={() => send(option)}>
                    {option}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="msg agent muted">
            <span className="msg-role">AI editor</span>
            Working&hellip;
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="composer">
        <textarea
          rows={2}
          style={{ flex: 1, resize: "none", border: "none", padding: "6px 4px" }}
          placeholder="Ask the AI editor, e.g. cut the first 10 seconds"
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
