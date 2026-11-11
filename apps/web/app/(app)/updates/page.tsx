"use client";
import { useState } from "react";
import { useSession } from "@/components/session";
import { Chip, ErrorBox, Loading, Panel } from "@/components/ui";
import { api, send, useLoad } from "@/lib/api";
import { whenFull } from "@/lib/format";
import { bytes, PACK_STATUS_LABEL, UPDATE_STATUS_LABEL } from "@/lib/updates";
import type { RulePackDetail, UpdatesInfo } from "@/lib/types";

export default function UpdatesPage() {
  const { me } = useSession();
  const u = useLoad(() => api<UpdatesInfo>("v1/updates"), []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<RulePackDetail | null>(null);
  const run = async (path: string, body: unknown) => {
    setBusy(true); setError("");
    try { await send("POST", path, body); u.reload(); if (open) setOpen(await api<RulePackDetail>(`v1/rule-packs/${open.id}`)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const d = u.data;
  const a = d?.app?.notice;
  const rn = d?.rules?.notice;
  if (me.role !== "admin") return <p className="text-sm">Só o administrador acessa as atualizações.</p>;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Atualizações</h1>
        <p className="text-sm text-muted">Nada é instalado sozinho. O servidor só avisa e, com a sua aprovação, baixa e confere o arquivo; quem instala é o administrador, no servidor. Pacotes de regras começam sem efeito, passam por uma fase de sombra e só valem quando você promove.</p>
      </div>
      {u.error && <ErrorBox message={u.error} onRetry={u.reload} />}
      {u.loading && !d && <Loading />}
      {error && <p role="alert" className="text-sm text-crit">{error}</p>}
      {d?.mode === "off" && <Panel title="Atualizações"><p className="text-sm" data-testid="updates-off">Desligado nesta instalação (sem licenciamento on-premise).</p></Panel>}
      {d?.mode === "onprem" && (
        <>
          <Panel title="Aplicação">
            <p className="text-sm" data-testid="app-installed">Versão instalada: <strong>{d.app?.installed}</strong></p>
            {!a && <p className="mt-2 text-sm text-muted" data-testid="app-none">Nenhuma versão nova. O aviso chega na renovação semanal da licença.</p>}
            {a && (
              <div className="mt-2 space-y-2 text-sm" data-testid="app-notice">
                <p className="flex flex-wrap items-center gap-2"><strong>Versão {a.version}</strong>
                  {a.security && <Chip>correção de segurança</Chip>}<Chip>{UPDATE_STATUS_LABEL[a.status] ?? a.status}</Chip><span className="text-muted">{bytes(a.size)}</span></p>
                {a.notes && <p className="whitespace-pre-wrap">{a.notes}</p>}
                {a.error && <p role="alert" className="text-crit">{a.error}</p>}
                {a.status === "available" && <button type="button" className="btn-primary" disabled={busy} onClick={() => void run("v1/updates/app/approve", { version: a.version })}>Aprovar o download</button>}
                {a.status === "failed" && <button type="button" className="btn" disabled={busy} onClick={() => void run("v1/updates/retry", { kind: "app" })}>Tentar de novo</button>}
                {a.status === "ready" && (
                  <div data-testid="app-ready" className="rounded border border-line p-3">
                    <p>Baixada e conferida (assinatura e SHA-256). Para instalar, no servidor, dentro da pasta do PromptShield:</p>
                    <pre className="mt-1 overflow-x-auto rounded bg-surface-2 p-2 font-mono text-xs">./atualizar.sh</pre>
                    <p className="mt-1 text-xs text-muted">SHA-256: <code>{a.sha256}</code> · aprovada por {a.approved_by} em {a.approved_at ? whenFull(a.approved_at) : "—"}. O script faz o backup antes de trocar a versão.</p>
                  </div>
                )}
              </div>
            )}
          </Panel>
          <Panel title="Pacotes de regras">
            <p className="text-sm" data-testid="rules-installed">Em vigor: <strong>{d.rules?.live ?? "padrão de fábrica"}</strong></p>
            {rn && rn.status === "available" && <p className="mt-2 text-sm" data-testid="rules-notice">Pacote <strong>{rn.version}</strong> disponível. Ele é baixado e guardado sem efeito. <span className="text-muted">{rn.notes}</span></p>}
            {rn?.status === "failed" && (
              <p role="alert" className="mt-2 text-sm text-crit" data-testid="rules-failed">Pacote {rn.version} recusado: {rn.error} <button type="button" className="btn ml-2" disabled={busy} onClick={() => void run("v1/updates/retry", { kind: "rules" })}>Tentar de novo</button></p>
            )}
            <ul className="mt-3 space-y-2" data-testid="packs">
              {(d.packs ?? []).map((p) => (
                <li key={p.id} className="rounded border border-line p-3 text-sm" data-testid="pack">
                  <p className="flex flex-wrap items-center gap-2"><strong>{p.version}</strong><Chip>{PACK_STATUS_LABEL[p.status]}</Chip><span className="text-muted">{p.rules} regra(s) · {p.hits} ocorrência(s)</span>
                    <button type="button" className="btn ml-auto" onClick={async () => setOpen(await api<RulePackDetail>(`v1/rule-packs/${p.id}`))}>Ver regras</button></p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {(p.status === "staged" || p.status === "retired") && <button type="button" className="btn" disabled={busy} onClick={() => void run(`v1/rule-packs/${p.id}/phase`, { to: "shadow" })}>Iniciar sombra</button>}
                    {p.status === "shadow" && <button type="button" className="btn-primary" disabled={busy} onClick={() => void run(`v1/rule-packs/${p.id}/phase`, { to: "active" })}>Promover a ativo</button>}
                    {(p.status === "shadow" || p.status === "active") && <button type="button" className="btn" disabled={busy} onClick={() => void run(`v1/rule-packs/${p.id}/phase`, { to: "retired" })}>Desativar</button>}
                  </div>
                </li>
              ))}
              {(d.packs ?? []).length === 0 && <li className="text-sm text-muted">Nenhum pacote recebido.</li>}
            </ul>
            {open && (
              <div className="mt-4 rounded border border-line p-3 text-sm" data-testid="pack-detail">
                <p className="font-semibold">Pacote {open.version}: {PACK_STATUS_LABEL[open.status]}</p>
                {Object.keys(open.weights).length > 0 && <p className="text-xs text-muted">Pesos de risco do pacote: {Object.entries(open.weights).map(([k, v]) => `${k}=${v}`).join(", ")} (os pesos da empresa prevalecem)</p>}
                <table className="mt-2 w-full text-left text-xs"><thead><tr><th>Regra</th><th>Categoria</th><th>Sombra</th><th>Ativo</th></tr></thead>
                  <tbody>{open.rules.map((r) => <tr key={r.id}><td>{r.rule}</td><td>{r.category}</td><td>{r.hits_shadow}</td><td>{r.hits_active}</td></tr>)}</tbody></table>
              </div>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
