import Link from "next/link";

export default function NotFound() {
  return (
    <main>
      <h1>Not found</h1>
      <p className="muted">That page, fighter or replay does not exist, or it is not yours to see.</p>
      <p>
        <Link href="/">Back to the replays</Link>
      </p>
    </main>
  );
}
