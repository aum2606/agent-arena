import Link from "next/link";
import { notFound } from "next/navigation";

import { getJson, type Replay } from "../../../lib/api";
import { Viewer } from "./viewer";

export const dynamic = "force-dynamic";

export default async function ReplayPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const replay = await getJson<Replay>(`/replays/${encodeURIComponent(id)}`);
  if (replay === null) notFound();
  return (
    <main>
      <p>
        <Link href="/">← All replays</Link>
      </p>
      <h1>{id}</h1>
      <Viewer replay={replay} />
    </main>
  );
}
