// Rendered per request so the status reflects the API now, not at build time.
export const dynamic = "force-dynamic";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

async function apiStatus(): Promise<string> {
  try {
    const response = await fetch(`${API_URL}/health`, { cache: "no-store" });
    const body: { status: string } = await response.json();
    return body.status;
  } catch {
    return "unreachable";
  }
}

export default async function Home() {
  return (
    <main>
      <h1>Agent Arena</h1>
      <p>API: {await apiStatus()}</p>
    </main>
  );
}
