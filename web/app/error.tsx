"use client";

// The message of the error is not shown: it can carry details of the server's failure.
export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <main>
      <h1>Something went wrong</h1>
      <p className="muted">
        The page could not be loaded. The server may be busy or restarting. Try again in a moment.
      </p>
      <button onClick={reset}>Try again</button>
    </main>
  );
}
