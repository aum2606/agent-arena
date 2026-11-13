import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { forwardedAddress } from "./client-address";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export interface User {
  id: number;
  handle: string;
}

/** Server-side fetch of the API that carries the visitor's session cookie and address along. */
async function request(path: string): Promise<Response> {
  const cookie = (await cookies()).toString();
  const address = forwardedAddress(process.env.CLIENT_IP_HEADER, await headers());
  return fetch(`${API_URL}${path}`, { cache: "no-store", headers: { cookie, ...address } });
}

/** The parsed JSON, or null on a 404; a 401 sends the visitor to sign in. Anything else is an error. */
export async function getJson<T>(path: string): Promise<T | null> {
  const response = await request(path);
  if (response.status === 401) redirect("/login");
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
