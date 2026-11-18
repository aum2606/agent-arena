import { getJson } from "../../lib/server-api";
import { Card } from "../components/Card";
import { PageHeader } from "../components/PageHeader";
import { DevLogin } from "./dev-login";
import styles from "./login.module.css";

export const dynamic = "force-dynamic";

interface AuthConfig {
  github: boolean;
  dev_login: boolean;
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  const config = await getJson<AuthConfig>("/auth/config").catch(() => null);
  return (
    <main className={styles.narrow}>
      <PageHeader title="Sign in" subtitle="Sign in to create fighters, spar against the house bot and play ranked matches." />
      <div className="stack">
        {/* Only this one fixed value is shown, so a crafted link cannot put its own text on the page. */}
        {error === "denied" && <p role="alert">GitHub did not let you in. You can try again.</p>}
        {config === null && <p role="alert">The server is unreachable. Try again in a moment.</p>}
        {config?.github && (
          <Card title="Continue with GitHub">
            <p className="muted">
              Agent Arena only keeps your GitHub username. It never sees your GitHub password and cannot act on your
              account.
            </p>
            {/* A plain link on purpose: the API redirects on to GitHub, which a client-side route cannot. */}
            <a href="/api/auth/github/login" className="button button-primary">
              Sign in with GitHub
            </a>
          </Card>
        )}
        {config && !config.github && !config.dev_login && (
          <Card title="Sign-in is not set up">
            <p className="muted">
              The person running this site needs to set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET (see
              docs/SELF_HOSTING.md).
            </p>
          </Card>
        )}
        {config?.dev_login && <DevLogin />}
      </div>
    </main>
  );
}
