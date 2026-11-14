/**
 * The header that tells the API which visitor a server-side fetch is for. The web server sits between
 * visitors and the API, so without it the API sees one address for everybody (D-063). The deployer
 * names the header (CLIENT_IP_HEADER) that their reverse proxy overwrites with the real address.
 */
export function forwardedAddress(name: string | undefined, incoming: Headers): Record<string, string> {
  const value = name ? incoming.get(name) : null;
  return name && value ? { [name]: value } : {};
}
