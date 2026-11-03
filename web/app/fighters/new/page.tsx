import Link from "next/link";
import { notFound } from "next/navigation";

import type { Options } from "../../../lib/fighters";
import { getJson } from "../../../lib/server-api";
import { FighterForm } from "../fighter-form";

export const dynamic = "force-dynamic";

export default async function NewFighterPage() {
  const options = await getJson<Options>("/fighters/options");
  if (options === null) notFound();
  return (
    <main>
      <p>
        <Link href="/fighters">← My fighters</Link>
      </p>
      <FighterForm options={options} />
    </main>
  );
}
