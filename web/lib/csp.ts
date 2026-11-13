/**
 * The Content-Security-Policy for one page request (D-064). Scripts and styles run only with this
 * request's nonce: Next adds it to the inline scripts it writes. `strict-dynamic` lets those scripts
 * load the bundles they need. React needs eval for debugging in development, never in production.
 * HTTPS (and so `upgrade-insecure-requests`) belongs to the reverse proxy in front of this server.
 */
export function contentSecurityPolicy(nonce: string, dev: boolean): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    `style-src 'self' 'nonce-${nonce}'`,
    "img-src 'self' blob: data:",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}
