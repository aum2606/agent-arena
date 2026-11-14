import { getJson } from "../../lib/server-api";
import { DevLogin } from "./dev-login";

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
    <main>
      <h1>Sign in</h1>
      {/* Only this one fixed value is shown, so a crafted link cannot put its own text on the page. */}
      {error === "denied" && <p role="alert">GitHub did not let you in. You can try again.</p>}
      {config === null && <p>The API is unreachable.</p>}
      {config?.github && (
        // A plain link on purpose: the API redirects on to GitHub, which a client-side route cannot.
        <p>
          <a href="/api/auth/github/login">Sign in with GitHub</a>
        </p>
      )}
      {config && !config.github && !config.dev_login && (
        <p className="muted">
          Sign-in is not set up: set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET (see .env.example).
        </p>
      )}
      {config?.dev_login && <DevLogin />}
    </main>
  );
}
