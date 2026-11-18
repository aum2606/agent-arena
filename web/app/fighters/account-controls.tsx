"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { errorText } from "../../lib/fighters";
import { Card } from "../components/Card";

/** Sign out on every device, or erase the account with its fighters and saved keys (D-078). */
export function AccountControls() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  async function leave(request: () => Promise<Response>, fallback: string) {
    setError(null);
    const response = await request();
    if (!response.ok) {
      setError(errorText(await response.json().catch(() => null), fallback));
      return;
    }
    router.push("/");
    router.refresh();
  }

  function signOutEverywhere() {
    return leave(() => fetch("/api/auth/logout-all", { method: "POST" }), "Could not sign out");
  }

  function deleteAccount() {
    const sure = window.confirm(
      "Delete your account? Your fighters, versions and saved API keys are erased and cannot be recovered. " +
        "Your sparring matches are deleted; ranked matches stay for the other player without your name.",
    );
    if (!sure) return;
    return leave(() => fetch("/api/auth/me", { method: "DELETE" }), "Could not delete the account");
  }

  return (
    <Card title="Your account" tone="danger">
      <p className="muted">
        Sign out on every device you are signed in on, or erase your account together with your fighters and the API keys
        saved for them.
      </p>
      <div className="row">
        <button onClick={signOutEverywhere}>Sign out everywhere</button>
        <button className="button-danger" onClick={deleteAccount}>
          Delete my account
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
    </Card>
  );
}
