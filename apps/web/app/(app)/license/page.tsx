"use client";
import { useState } from "react";
import { useSession } from "@/components/session";
import { Chip, ErrorBox, Loading, Panel } from "@/components/ui";
import { api, send, useLoad } from "@/lib/api";
import { whenFull } from "@/lib/format";
import { STATE_EFFECT, STATE_LABEL } from "@/lib/license";
import type { LicenseStatus } from "@/lib/types";

const row = (label: string, value: string | number | null | undefined) => (
  <div className="contents"><dt className="text-muted">{label}</dt><dd>{value ?? "—"}</dd></div>
);
const date = (v?: string | null) => (v ? whenFull(v) : "—");

export default function LicensePage() {
  const { me } = useSession();
  const s = useLoad(() => api<LicenseStatus>("v1/license/status"), []);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const isAdmin = me.role === "admin";
  const act = async (path: string, body?: unknown) => {
    setBusy(true); setError(""); setDone("");
    try {
      await send("POST", path, body);
      setDone(path.endsWith("activate") ? "Instalação ativada." : "Autorização renovada.");
      setCode("");
      s.reload();
      setTimeout(() => location.reload(), 600);      // a faixa do topo e os bloqueios dependem do estado novo
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const d = s.data;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Licença</h1>
        <p className="text-sm text-muted">Situação do contrato e da autorização desta instalação. Nenhum estado apaga dados nem interrompe as ferramentas dos funcionários; se a inspeção parar, isso aparece aqui, no topo do console e nos sensores.</p>
      </div>
      {s.error && <ErrorBox message={s.error} onRetry={s.reload} />}
      {s.loading && !d && <Loading />}
      {d && d.mode === "off" && <Panel title="Licenciamento por autorização"><p className="text-sm" data-testid="license-off">Desligado nesta instalação (<code>LICENSE_MODE=off</code>). Em instalações no servidor do cliente, esta página mostra o contrato e a autorização.</p></Panel>}
      {d && d.mode === "onprem" && (
        <>
          <Panel title="Situação">
            <p className="mb-2 flex flex-wrap items-center gap-2"><Chip>{STATE_LABEL[d.state]}</Chip>
              <span className={`text-sm font-semibold ${d.inspecting ? "" : "text-crit"}`} data-testid="inspecting">{d.inspecting ? "Inspeção funcionando" : "Inspeção PARADA"}</span></p>
            <p className="text-sm" data-testid="license-message">{d.message}</p>
            <p className="mt-2 text-xs text-muted">{STATE_EFFECT[d.state]}</p>
          </Panel>
          <Panel title="Contrato e autorização">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm" data-testid="license-details">
              {row("Cliente", d.customer)}
              {row("Máquinas permitidas", d.max_devices)}
              {row("Contrato até", date(d.contract_end))}
              {row("Tolerância até", date(d.tolerance_end))}
              {row("Autorização local vale até", date(d.auth_expires))}
              {row("Ao encerrar o contrato", d.on_end === "keep_inspection" ? "a inspeção continua" : d.on_end === "stop_inspection" ? "a inspeção para" : null)}
              {row("Último contato bem-sucedido", date(d.last_success_at))}
              {row("Última tentativa", date(d.last_attempt_at))}
              {row("Último erro", d.last_error)}
              {row("Autorização nº", d.serial)}
              {row("Identificador desta instalação", d.installation_id)}
            </dl>
            {d.problem && <p role="alert" className="mt-2 text-sm text-crit">{d.problem}</p>}
          </Panel>
          {isAdmin && (
            <Panel title={d.state === "nao_ativado" ? "Ativar esta instalação" : "Renovar agora"}>
              {d.state === "nao_ativado" ? (
                <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); void act("v1/license/activate", { code: code.trim() }); }}>
                  <div><label htmlFor="code" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Código de ativação (uso único)</label>
                    <input id="code" className="field w-96 max-w-full font-mono" value={code} minLength={10} maxLength={200} autoComplete="off" onChange={(e) => setCode(e.target.value)} placeholder="psa_xxxxxxxx_…" /></div>
                  <button className="btn-primary" disabled={busy || code.trim().length < 10}>Ativar</button>
                </form>
              ) : (
                <div className="flex flex-wrap items-center gap-3">
                  <button type="button" className="btn" disabled={busy} onClick={() => void act("v1/license/renew")}>Renovar agora</button>
                  <span className="text-xs text-muted">O servidor já renova sozinho (por exemplo, uma vez por dia). Use isto depois de o fornecedor renovar o contrato.</span>
                </div>
              )}
              {error && <p role="alert" className="mt-2 text-sm text-crit">{error}</p>}
              {done && <p role="status" className="mt-2 text-sm">{done}</p>}
              {!d.server_configured && <p className="mt-2 text-xs text-muted">Atenção: o servidor ainda não tem <code>LICENSE_SERVER_URL</code> e <code>LICENSE_PUBLIC_KEY</code> configurados.</p>}
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
