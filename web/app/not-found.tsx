import Link from "next/link";

import { EmptyState } from "./components/EmptyState";

export default function NotFound() {
  return (
    <main>
      <EmptyState
        title="Not found"
        action={
          <Link href="/" className="button button-primary">
            Back to the replays
          </Link>
        }
      >
        That page, fighter or replay does not exist, or it is not yours to see.
      </EmptyState>
    </main>
  );
}
