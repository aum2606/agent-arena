import Link from "next/link";

import type { FighterView } from "../../lib/fighters";
import { getJson } from "../../lib/server-api";

export const dynamic = "force-dynamic";

export default async function FightersPage() {
  const fighters = (await getJson<FighterView[]>("/fighters")) ?? [];
  return (
    <main>
      <h1>My fighters</h1>
      <p>
        <Link href="/fighters/new">New fighter</Link>
      </p>
      {fighters.length === 0 ? (
        <p className="muted">You have no fighters yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Version</th>
              <th>Model</th>
              <th>Verified</th>
            </tr>
          </thead>
          <tbody>
            {fighters.map((f) => (
              <tr key={f.id}>
                <td>
                  <Link href={`/fighters/${f.id}`}>{f.name}</Link>
                </td>
                <td>{f.version}</td>
                <td>
                  {f.provider} / {f.model}
                </td>
                <td>{f.verified ? "yes" : "not yet"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
