import Link from "next/link";
import { notFound } from "next/navigation";

import type { Options } from "../../../lib/fighters";
import { getJson } from "../../../lib/server-api";
import { Card } from "../../components/Card";
import { PageHeader } from "../../components/PageHeader";
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
      <PageHeader
        title="New fighter"
        subtitle="Choose a model, give it a personality, and add your own API key. You can change any of it later: each save is a new version."
      />
      <Card>
        <FighterForm options={options} />
      </Card>
    </main>
  );
}
