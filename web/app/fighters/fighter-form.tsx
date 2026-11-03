"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { errorText, type FighterView, type Options } from "../../lib/fighters";

interface Props {
  options: Options;
  /** Editing makes a new version of this fighter; without it the form creates one. */
  fighter?: FighterView;
}

export function FighterForm({ options, fighter }: Props) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [provider, setProvider] = useState(fighter?.provider ?? options.providers[0] ?? "");
  const [model, setModel] = useState(fighter?.model ?? "");
  const [persona, setPersona] = useState(fighter?.persona ?? options.templates[0]?.persona ?? "");
  const [apiKey, setApiKey] = useState("");
  const [cap, setCap] = useState(String(fighter?.daily_match_cap ?? 10));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const body: Record<string, unknown> = {
      provider,
      model,
      persona,
      daily_match_cap: Number(cap),
    };
    if (apiKey) body.api_key = apiKey;
    if (!fighter) body.name = name;
    const response = await fetch(fighter ? `/api/fighters/${fighter.id}/versions` : "/api/fighters", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const saved = await response.json().catch(() => null);
    setSaving(false);
    if (!response.ok) {
      setError(errorText(saved, "Could not save the fighter"));
      return;
    }
    setApiKey("");
    router.push(`/fighters/${saved.id}`);
    router.refresh();
  }

  return (
    <form onSubmit={submit} className="form">
      <h2>{fighter ? `Edit ${fighter.name} (saves as version ${fighter.version + 1})` : "New fighter"}</h2>
      {!fighter && (
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} required pattern="[A-Za-z0-9_\-]{1,32}" />
        </label>
      )}
      <label>
        Provider
        <select value={provider} onChange={(e) => setProvider(e.target.value)}>
          {options.providers.map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
      </label>
      <label>
        Model
        <input value={model} onChange={(e) => setModel(e.target.value)} required maxLength={100} />
      </label>
      <label>
        Persona
        <select
          value=""
          onChange={(e) => {
            const template = options.templates.find((t) => t.name === e.target.value);
            if (template) setPersona(template.persona);
          }}
        >
          <option value="">Start from a template…</option>
          {options.templates.map((t) => (
            <option key={t.name}>{t.name}</option>
          ))}
        </select>
        <textarea value={persona} onChange={(e) => setPersona(e.target.value)} rows={5} required maxLength={2000} />
      </label>
      <label>
        API key {fighter ? `(saved, ends in ${fighter.key_hint}; leave blank to keep it)` : ""}
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          autoComplete="off"
          required={!fighter}
          minLength={8}
        />
      </label>
      <label>
        Matches per day
        <input type="number" min={1} max={50} value={cap} onChange={(e) => setCap(e.target.value)} required />
      </label>
      <p className="muted">
        The key is encrypted on the server and never shown again; only your fighter&apos;s turns use it.
      </p>
      <button type="submit" disabled={saving}>
        {saving ? "Saving…" : "Save"}
      </button>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
