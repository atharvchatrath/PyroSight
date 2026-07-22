import type { Metadata } from "next";
import "./globals.css";
import { UplinkProvider } from "@/lib/uplink";

export const metadata: Metadata = {
  title: "PyroSight",
  description:
    "AI-powered wearable firefighter assistance platform — situational awareness in zero visibility.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="font-mono">
        <UplinkProvider>{children}</UplinkProvider>
      </body>
    </html>
  );
}
