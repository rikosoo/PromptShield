"use client";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { ErrorBox, Loading } from "@/components/ui";
import { api, useLoad } from "@/lib/api";
import { passwordOk, passwordRules } from "@/lib/password";
import type { Me } from "@/lib/types";

/** Troca de senha. Fica FORA do menu do console de propósito: com senha provisória é a única tela que funciona. */
export default function ChangePasswordPage() {
  const me = useLoad(() => api<Me>("v1/me"), []);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const rules = passwordRules(next);
  const forced = !!me.data?.must_change_password;
  const ready = !!current && passwordOk(next) && next === again && next !== current;

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    setBusy(true);
    setError(null);
    const r = await fetch("/api/auth/password", { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "promptshield" }, body: JSON.stringify({ current_password: current, new_password: next }) });
    if (r.ok) { location.assign("/"); return; }
    setError((await r.json().catch(() => ({}))).error ?? "Não foi possível trocar a senha.");
    setBusy(false);
  }
  async function logout() {
    await fetch("/api/auth/logout", { method: "POST", headers: { "X-Requested-With": "promptshield" } });
    location.assign("/login");
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4">
      <div className="rounded-md border border-line bg-panel p-6">
        <h1 className="text-xl font-bold">{forced ? "Defina a sua senha" : "Alterar senha"}</h1>
        {me.loading && !me.data && <div className="mt-4"><Loading /></div>}
        {me.error && <div className="mt-4"><ErrorBox message={me.error} onRetry={me.reload} /></div>}
        {me.data && !me.data.has_password && <p role="note" className="mt-4 rounded border border-med bg-med-bg p-2 text-sm text-med">Esta conta entra pelo login da empresa e não tem senha local para trocar.</p>}
        {me.data?.has_password && (
          <form onSubmit={submit} className="mt-4 space-y-3" aria-label="Trocar a senha">
            {forced && <p role="note" className="rounded border border-med bg-med-bg p-2 text-sm text-med">A senha que você recebeu é <strong>provisória</strong>. Escolha a sua para continuar.</p>}
            <p className="text-xs text-muted">{me.data.email}</p>
            <div><label htmlFor="cur" className="mb-1 block text-sm font-medium">{forced ? "Senha provisória" : "Senha atual"}</label>
              <input id="cur" type="password" required autoComplete="current-password" maxLength={256} className="field w-full" value={current} onChange={(e) => setCurrent(e.target.value)} /></div>
            <div><label htmlFor="new" className="mb-1 block text-sm font-medium">Nova senha</label>
              <input id="new" type="password" required autoComplete="new-password" maxLength={128} className="field w-full" value={next} onChange={(e) => setNext(e.target.value)} aria-describedby="rules" /></div>
            <ul id="rules" className="space-y-0.5 text-xs" data-testid="password-rules" aria-label="Requisitos da senha">
              {rules.map((r) => <li key={r.id} className={r.ok ? "text-low" : "text-muted"}><span aria-hidden="true">{r.ok ? "✓" : "○"}</span> {r.label}<span className="sr-only">{r.ok ? " (cumprido)" : " (falta)"}</span></li>)}
            </ul>
            <div><label htmlFor="again" className="mb-1 block text-sm font-medium">Repita a nova senha</label>
              <input id="again" type="password" required autoComplete="new-password" maxLength={128} className="field w-full" value={again} onChange={(e) => setAgain(e.target.value)} />
              {again && next !== again && <p role="status" className="mt-1 text-xs text-high">As senhas não são iguais.</p>}
              {next && current && next === current && <p role="status" className="mt-1 text-xs text-high">A nova senha precisa ser diferente da atual.</p>}</div>
            {error && <p role="alert" className="rounded border border-crit bg-crit-bg p-2 text-sm text-crit">{error}</p>}
            <button type="submit" className="btn-primary w-full" disabled={busy || !ready}>{busy ? "Salvando…" : "Salvar nova senha"}</button>
          </form>
        )}
        <p className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
          {!forced && <Link href="/" className="underline">Voltar ao console</Link>}
          <button type="button" className="underline" onClick={() => void logout()}>Sair</button>
        </p>
      </div>
    </main>
  );
}
