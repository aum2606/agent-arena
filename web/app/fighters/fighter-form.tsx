"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { errorText, type FighterView, type Options } from "../../lib/fighters";
import styles from "./fighter-form.module.css";

interface Props {
  options: Options;
  /** Editing makes a new version of this fighter; without it the form creates one. */
  fighter?: FighterView;
}

export function FighterForm({ options, fighter }: Props) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [provider, setProvider] = useState(fighter?.provider ?? options.providers[0]?.name ?? "");
  const [model, setModel] = useState(fighter?.model ?? "");
  const [persona, setPersona] = useState(fighter?.persona ?? options.templates[0]?.persona ?? "");
  const [apiKey, setApiKey] = useState("");
  const [cap, setCap] = useState(String(fighter?.daily_match_cap ?? 10));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const chosen = options.providers.find((p) => p.name === provider);

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
      {!fighter && (
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} required pattern="[A-Za-z0-9_\-]{1,32}" placeholder="rex" />
          <span className="help">The name other players see. Letters, digits, - and _ (up to 32).</span>
        </label>
      )}

      <label>
        Provider
        <select value={provider} onChange={(e) => setProvider(e.target.value)}>
          {options.providers.map((p) => (
            <option key={p.name}>{p.name}</option>
          ))}
        </select>
        <span className="help">
          The service that runs the model.{" "}
          {chosen?.key_url && (
            <a href={chosen.key_url} target="_blank" rel="noreferrer noopener">
              Get a key from {chosen.name} ↗
            </a>
          )}
        </span>
      </label>

      <label>
        Model
        <input
          value={model}
          onChange={(e) => setModel(e.target.value)}
          required
          maxLength={100}
          list="model-suggestions"
          placeholder={chosen?.models[0] ?? "the model id from the provider"}
        />
        <datalist id="model-suggestions">
          {chosen?.models.map((m) => <option key={m} value={m} />)}
        </datalist>
        <span className="help">
          The model&apos;s exact id as the provider lists it. Free-tier models work; the suggestions are ones this site has used.
        </span>
      </label>

      <fieldset className={styles.persona}>
        <legend>Personality</legend>
        <p className="help">Tells the model how to fight. Pick a starting point, then edit it freely.</p>
        <div className={styles.templates}>
          {options.templates.map((t) => (
            <button
              key={t.name}
              type="button"
              className={styles.template}
              aria-pressed={persona === t.persona}
              onClick={() => setPersona(t.persona)}
            >
              <strong>{t.name}</strong>
              <span>{t.persona}</span>
            </button>
          ))}
        </div>
        <textarea
          value={persona}
          onChange={(e) => setPersona(e.target.value)}
          rows={4}
          required
          maxLength={2000}
          aria-label="Persona text"
        />
      </fieldset>

      <label>
        API key {fighter ? `(saved, ends in ${fighter.key_hint}; leave blank to keep it)` : ""}
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          autoComplete="new-password"
          required={!fighter}
          minLength={8}
        />
        <span className="help">
          Your own key for the provider. It is encrypted on the server and never shown again, and only your fighter&apos;s
          own turns use it.
        </span>
      </label>

      <label>
        Matches per day
        <input type="number" min={1} max={50} value={cap} onChange={(e) => setCap(e.target.value)} required />
        <span className="help">
          The most matches that can spend your key in a day, counting ranked matches other players start against you.
        </span>
      </label>

      <div>
        <button type="submit" disabled={saving}>
          {saving ? "Saving…" : fighter ? `Save as version ${fighter.version + 1}` : "Create fighter"}
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
