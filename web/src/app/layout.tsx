import type { Metadata } from "next";
import { Geist_Mono, Plus_Jakarta_Sans, Unbounded } from "next/font/google";

import { AppShell } from "@/components/app-shell";

import "./globals.css";

// latin-ext carries the peso sign (U+20B1); latin alone doesn't.
const unbounded = Unbounded({
  subsets: ["latin", "latin-ext"],
  weight: ["500", "700"],
  variable: "--font-unbounded",
});
const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-jakarta",
});
const geistMono = Geist_Mono({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500"],
  variable: "--font-geist-mono",
});

export const metadata: Metadata = {
  title: "Kako",
  description: "The household financial planner that learns why.",
};

// The saved theme and sidebar, before the first paint (dark and open when none is saved). Only the
// known values are applied: "light" or "dark" (theme-toggle.tsx), "collapsed" (src/lib/sidebar.ts).
const THEME_SCRIPT = `(function(){try{var d=document.documentElement,t=localStorage.getItem("kako-theme");if(t==="light"||t==="dark")d.setAttribute("data-theme",t);if(localStorage.getItem("kako-sidebar")==="collapsed")d.setAttribute("data-sidebar","collapsed")}catch(e){}})()`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      data-theme="dark"
      suppressHydrationWarning
      className={`${unbounded.variable} ${jakarta.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="h-full font-sans">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
