import { cookies } from "next/headers";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export interface User {
  id: number;
  handle: string;
}

/** Server-side fetch of the API that carries the visitor's session cookie along. */
async function request(path: string): Promise<Response> {
  const cookie = (await cookies()).toString();
  return fetch(`${API_URL}${path}`, { cache: "no-store", headers: { cookie } });
}

/** The parsed JSON, or null when the API answers 404. Anything else is an error. */
export async function getJson<T>(path: string): Promise<T | null> {
  const response = await request(path);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`API ${path} returned ${response.status}`);
  return response.json();
}

/** Who is signed in, or null for a visitor (also when the API is unreachable). */
export async function currentUser(): Promise<User | null> {
  try {
    const response = await request("/auth/me");
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}
