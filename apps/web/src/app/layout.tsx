import type { Metadata } from "next";
import { connection } from "next/server";
import type { ReactNode } from "react";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: { default: "Mixt AI", template: "%s · Mixt AI" },
  description: "Mixt Academy sales and CRM dashboard",
  robots: { index: false, follow: false },
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  // Render every page per request so it carries that request's CSP nonce (src/proxy.ts).
  await connection();
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
