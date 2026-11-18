"use client";

import "./globals.css";

// Replaces the whole page when the root layout itself fails, so it brings its own <html>.
export default function GlobalError({ reset }: { error: Error; reset: () => void }) {
  return (
    <html lang="en">
      <body>
        <main className="page">
          <h1>Agent Arena is having trouble</h1>
          <p className="muted">Try again in a moment.</p>
          <button onClick={reset}>Try again</button>
        </main>
      </body>
    </html>
  );
}
