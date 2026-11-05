import type { ReactNode } from "react";
import "./globals.css";

export const metadata = { title: "PromptShield" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="pt-BR" data-theme="light">
      <body className="min-h-screen bg-bg text-fg antialiased">{children}</body>
    </html>
  );
}
