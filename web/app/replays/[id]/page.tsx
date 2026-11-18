import Link from "next/link";
import { notFound } from "next/navigation";

import { sideLabel, type Replay } from "../../../lib/api";
import { formatDate, modeLabel } from "../../../lib/labels";
import { getJson } from "../../../lib/server-api";
import { PageHeader } from "../../components/PageHeader";
import { Viewer } from "./viewer";

export const dynamic = "force-dynamic";

export default async function ReplayPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const replay = await getJson<Replay>(`/replays/${encodeURIComponent(id)}`);
  if (replay === null) notFound();
  const { summary } = replay;
  // Older logs carry no fighter names: the match id is all there is to call them by.
  const named = summary.name_a !== null && summary.name_b !== null;
  const when = formatDate(summary.ended_at);
  return (
    <main>
      <p>
        <Link href="/">← Replays</Link>
      </p>
      <PageHeader
        title={named ? `${sideLabel(summary, "a")} vs ${sideLabel(summary, "b")}` : id}
        subtitle={`${modeLabel(summary.mode)}${when ? ` · ${when}` : ""} · ${summary.turn_count} turns`}
      />
      <Viewer replay={replay} />
    </main>
  );
}
