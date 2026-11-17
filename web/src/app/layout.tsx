import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kako",
  description: "The household financial planner that learns why.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col font-sans">
        <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-8 px-6 py-12">
          {children}
        </main>
        <footer className="border-t border-stone-200 px-6 py-4 text-center text-sm text-stone-500 dark:border-stone-800">
          Synthetic data only. Not financial advice.
        </footer>
      </body>
    </html>
  );
}
