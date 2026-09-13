import type { Metadata } from "next";
import { Sora, Share_Tech_Mono, Orbitron, Rajdhani } from "next/font/google";
import "./globals.css";
import { FreyaSocketProvider } from "./components/FreyaSocketProvider";
import Link from "next/link";

const sora = Sora({
  subsets: ["latin"],
  variable: "--font-sans",
});

const shareTechMono = Share_Tech_Mono({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-mono",
});

const orbitron = Orbitron({
  weight: "700",
  subsets: ["latin"],
  variable: "--font-orbitron",
});

const rajdhani = Rajdhani({
  weight: ["500", "600"],
  subsets: ["latin"],
  variable: "--font-rajdhani",
});

export const metadata: Metadata = {
  title: "F.R.E.Y.A V3.0 — Archival System",
  description: "Crimson command core online. Neural pathways synchronized for directive input.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      // Browser extensions inject root attributes before hydration (e.g. crxlauncher).
      // Tolerate those here; descendant hydration checks remain enabled.
      suppressHydrationWarning
      className={`${sora.variable} ${shareTechMono.variable} ${orbitron.variable} ${rajdhani.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-surface text-parchment font-sans"><FreyaSocketProvider><nav className="px-6 py-2 text-xs flex gap-6 border-b border-white/10"><Link href="/">Freya command</Link><Link href="/trading">Trading Lab · Simulation</Link></nav>{children}</FreyaSocketProvider></body>
    </html>
  );
}
