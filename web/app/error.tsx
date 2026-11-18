"use client";

import { EmptyState } from "./components/EmptyState";

// The message of the error is not shown: it can carry details of the server's failure.
export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <main>
      <EmptyState
        title="Something went wrong"
        action={<button onClick={reset}>Try again</button>}
      >
        The page could not be loaded. The server may be busy or restarting. Try again in a moment.
      </EmptyState>
    </main>
  );
}
