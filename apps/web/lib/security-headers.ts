/** Cabeçalhos de segurança do console (puros, testados). `script-src` precisa de 'unsafe-inline' por causa dos scripts em linha que o
 *  Next.js injeta; não usamos eval em produção. Todo o resto é restritivo: nada de outros domínios, nada de iframes, nada de plugins. */
export function contentSecurityPolicy(dev = false): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

export function securityHeaders(dev = false): { key: string; value: string }[] {
  return [
    { key: "Content-Security-Policy", value: contentSecurityPolicy(dev) },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "no-referrer" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()" },
    { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
    { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
    // o navegador só respeita HSTS em respostas https; em http é ignorado
    { key: "Strict-Transport-Security", value: "max-age=15552000" },
  ];
}
