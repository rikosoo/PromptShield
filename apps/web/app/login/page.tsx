"use client";
import { useEffect, useState, type FormEvent } from "react";

export default function LoginPage() {
  const [mode, setMode] = useState<"mock" | "oidc" | null>(null);
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch("/api/auth/mode").then((r) => r.json()).then((j) => setMode(j.mode)).catch(() => setError("Não foi possível falar com o servidor."));
    const e = new URLSearchParams(location.search).get("erro");
    if (e) setError(e);
  }, []);

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    setBusy(true);
    setError(null);
    const r = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "promptshield" }, body: JSON.stringify({ email }) });
    if (r.ok) { location.assign("/"); return; }
    setError((await r.json().catch(() => ({}))).error ?? "Não foi possível entrar.");
    setBusy(false);
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4">
      <div className="rounded-md border border-line bg-panel p-6">
        <h1 className="text-xl font-bold">PromptShield</h1>
        <p className="mt-1 text-sm text-muted">Console de segurança para uso de IA.</p>
        {error && <p role="alert" className="mt-4 rounded border border-crit bg-crit-bg p-2 text-sm text-crit">{error}</p>}
        {mode === "oidc" && (
          <a href="/api/auth/oidc/start" className="btn-primary mt-5 inline-block">Entrar com a conta da empresa</a>
        )}
        {mode === "mock" && (
          <form onSubmit={submit} className="mt-5 space-y-3">
            <p className="rounded border border-med bg-med-bg p-2 text-xs text-med">Login simulado de desenvolvimento (AUTH_MODE=mock). Não use em produção.</p>
            <div>
              <label htmlFor="email" className="mb-1 block text-sm font-medium">E-mail</label>
              <input id="email" name="email" type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} className="field w-full" />
            </div>
            <button type="submit" className="btn-primary w-full" disabled={busy}>{busy ? "Entrando…" : "Entrar"}</button>
          </form>
        )}
        {mode === null && !error && <p role="status" className="mt-5 text-sm text-muted">Carregando…</p>}
        <p className="mt-5 text-xs text-muted">O tenant é definido pelo seu cadastro: cada e-mail pertence a uma única empresa.</p>
      </div>
    </main>
  );
}
