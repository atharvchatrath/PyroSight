// The wordmark, in one place.
//
// It was drifting: the landing page used one orange, the live and dashboard
// headers used the danger red reserved for fire. A logo that changes colour
// between screens reads as three different products, and on this palette it
// also mis-signals — danger red means fire everywhere else in the interface,
// so a brand mark wearing it is claiming something it does not mean.

import Link from "next/link";

export default function Wordmark({
  size = "md",
  href = "/",
}: {
  size?: "sm" | "md" | "lg";
  href?: string | null;
}) {
  const px = size === "lg" ? 24 : size === "md" ? 19 : 15;
  const mark = (
    <span
      className="font-semibold tracking-[0.3em] text-bright whitespace-nowrap"
      style={{ fontSize: px, lineHeight: 1 }}
    >
      PYRO<span style={{ color: "#ff6a00" }}>SIGHT</span>
    </span>
  );
  if (!href) return mark;
  return (
    <Link href={href} className="transition-opacity hover:opacity-80">
      {mark}
    </Link>
  );
}
