"use client";

// The AI speaks in cards, not popups.
//
// A modal popup in a burning building is an obstacle; these are small frosted
// notes that rise in, hold long enough to read once, and leave on their own.
// At most three live at a time and duplicates never stack, because the fastest
// way to make someone ignore the AI is to let it repeat itself.

import { useEffect, useRef, useState } from "react";
import { COLOR } from "@/lib/design";

interface Card {
  id: number;
  text: string;
  born: number;
  tone: "info" | "warn";
}

const TTL_MS = 6500;
const MAX = 3;

export default function AssistantStack({
  message,
  tone = "info",
  align = "right",
}: {
  message: string | null;
  tone?: "info" | "warn";
  align?: "right" | "center";
}) {
  const [cards, setCards] = useState<Card[]>([]);
  const seq = useRef(0);
  const lastText = useRef<string | null>(null);

  useEffect(() => {
    if (!message) return;
    if (message === lastText.current) return;
    lastText.current = message;
    setCards((prev) =>
      [...prev, { id: ++seq.current, text: message, born: Date.now(), tone }].slice(-MAX)
    );
  }, [message, tone]);

  // Single sweeper for the whole stack — one timer, not one per card.
  useEffect(() => {
    if (cards.length === 0) return;
    const id = setInterval(() => {
      const now = Date.now();
      setCards((prev) => prev.filter((c) => now - c.born < TTL_MS));
    }, 400);
    return () => clearInterval(id);
  }, [cards.length]);

  if (cards.length === 0) return null;

  return (
    <div
      className={`flex flex-col gap-2 ${
        align === "center" ? "items-center" : "items-end"
      }`}
    >
      {cards.map((c, i) => {
        const age = Date.now() - c.born;
        const leaving = age > TTL_MS - 700;
        const color = c.tone === "warn" ? COLOR.warn : COLOR.nav;
        return (
          <div
            key={c.id}
            className="panel-float animate-riseIn flex items-start gap-2.5 px-3 py-2 max-w-[22rem]
              transition-all duration-500 ease-hud"
            style={{
              opacity: leaving ? 0 : 1 - i * 0.18,
              transform: leaving ? "translateY(-4px)" : "none",
              borderColor: `${color}55`,
            }}
          >
            <svg viewBox="0 0 24 24" className="w-4 h-4 mt-[1px] shrink-0" fill="none"
              stroke={color} strokeWidth={1.6} strokeLinecap="round">
              <path d="M12 3.5 13.9 9l5.6 1.5-4.2 3.9 1 5.6L12 17.3 7.7 20l1-5.6-4.2-3.9L10.1 9z" />
            </svg>
            <span className="text-[13px] leading-snug text-bright">{c.text}</span>
          </div>
        );
      })}
    </div>
  );
}
