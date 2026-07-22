"use client";

// Voice / command interface. Big glove-friendly quick buttons, a text field,
// and — where the browser exposes SpeechRecognition — a push-to-talk mic.
// All paths funnel into the same offline backend grammar; on the Pi the
// same grammar is fed by Vosk running locally.

import { useCallback, useRef, useState } from "react";

const QUICK: { label: string; text: string; danger?: boolean }[] = [
  { label: "FIND EXIT", text: "find exit" },
  { label: "LOCATE PERSON", text: "locate person" },
  { label: "SEARCH ROOM", text: "search room" },
  { label: "RETURN TO ENTRY", text: "return to entry" },
  { label: "SHOW THERMAL", text: "show thermal" },
  { label: "SHOW CAMERA", text: "show camera" },
  { label: "HIGHLIGHT DOORS", text: "highlight doors" },
  { label: "HIDE LABELS", text: "hide labels" },
  { label: "BRIGHTER", text: "increase brightness" },
  { label: "DIMMER", text: "lower brightness" },
  { label: "MARK ENTRY", text: "mark entry" },
  { label: "REPEAT ALERT", text: "repeat last alert" },
  { label: "⚠ EMERGENCY", text: "emergency mode", danger: true },
  { label: "CLEAR EMERGENCY", text: "cancel emergency" },
  { label: "STAND DOWN", text: "stand down" },
];

export default function CommandBar({
  onCommand,
}: {
  onCommand: (text: string) => void;
}) {
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const recRef = useRef<{ stop: () => void } | null>(null);

  const submit = useCallback(
    (t: string) => {
      const trimmed = t.trim();
      if (trimmed) onCommand(trimmed);
      setText("");
    },
    [onCommand]
  );

  const toggleMic = useCallback(() => {
    const w = window as unknown as {
      SpeechRecognition?: new () => SpeechRecognitionLike;
      webkitSpeechRecognition?: new () => SpeechRecognitionLike;
    };
    const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!Ctor) {
      submit("status");
      return;
    }
    if (listening) {
      recRef.current?.stop();
      setListening(false);
      return;
    }
    const rec = new Ctor();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = (ev) => {
      const transcript = ev.results?.[0]?.[0]?.transcript;
      if (transcript) submit(transcript);
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  }, [listening, submit]);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        {QUICK.map((q) => (
          <button
            key={q.label}
            className={`btn text-xs ${q.danger ? "border-danger text-danger" : ""}`}
            onClick={() => submit(q.text)}
          >
            {q.label}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <button
          className={`btn shrink-0 ${listening ? "border-danger text-danger animate-alarm" : ""}`}
          onClick={toggleMic}
          title="Push to talk (browser STT; Vosk offline on the Pi)"
        >
          {listening ? "● LISTENING" : "🎙 VOICE"}
        </button>
        <input
          className="flex-1 min-h-[48px] px-3 rounded border border-edge bg-ink text-bright placeholder-dim focus:outline-none focus:ring-2 focus:ring-accent"
          placeholder='Type a command… e.g. "find exit"'
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit(text)}
        />
        <button className="btn shrink-0" onClick={() => submit(text)}>
          SEND
        </button>
      </div>
    </div>
  );
}

interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((ev: {
    results?: { [i: number]: { [j: number]: { transcript?: string } } };
  }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
}
