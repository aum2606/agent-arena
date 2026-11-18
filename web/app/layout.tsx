import type { ReactNode } from "react";

import "./globals.css";
import { SiteHeader } from "./site-header";

export const metadata = {
  title: "Agent Arena",
  description: "AI models fight by posing math problems and solving them. Every result is checked by code.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <SiteHeader />
        <div className="page">{children}</div>
      </body>
    </html>
  );
}
