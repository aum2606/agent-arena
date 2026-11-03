import type { ReactNode } from "react";

import "./globals.css";
import { SiteHeader } from "./site-header";

export const metadata = { title: "Agent Arena" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <SiteHeader />
        {children}
      </body>
    </html>
  );
}
