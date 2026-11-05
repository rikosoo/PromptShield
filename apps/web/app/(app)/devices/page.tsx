"use client";
import { useState, type FormEvent } from "react";
import { Dialog } from "@/components/Dialog";
import { useSession } from "@/components/session";
import { Empty, ErrorBox, Kpi, Loading, Panel } from "@/components/ui";
import { api, send, useLoad } from "@/lib/api";
import { whenFull } from "@/lib/format";
import type { DevicesOut, EnrollTokenRow } from "@/lib/types";

const TOOL_LABEL: Record<string, string> = { claude_code: "Claude Code", github_copilot_cli: "GitHub Copilot CLI", browser_extension: "Extensão do navegador (preparada; falta carregar)" };

export default function DevicesPage() {
  const { me } = useSession();
  const isAdmin = me.role === "admin";
  const devices = useLoad(() => api<DevicesOut>("v1/devices"), []);
  const tokens = useLoad(() => (isAdmin ? api<EnrollTokenRow[]>("v1/enrollment-tokens") : Promise.resolve([] as EnrollTokenRow[])), [isAdmin]);
  const [name, setName] = useState("");
  const [days, setDays] = useState(14);
  const [maxUses, setMaxUses] = useState(1000);
  const [apiUrl, setApiUrl] = useState("https://api.suaempresa.exemplo");
  const [created, setCreated] = useState<{ token: string; name: string } | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); devices.reload(); tokens.reload(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Falhou." }); } finally { setBusy(false); }
  }
  const create = (ev: FormEvent) => { ev.preventDefault(); void run(async () => { const r = await send<{ token: string; name: string }>("POST", "v1/enrollment-tokens", { name, expires_in_days: days, max_uses: maxUses }); setCreated({ token: r.token, name: r.name }); setName(""); }, "Token criado."); };
  const revokeToken = (t: EnrollTokenRow) => { if (confirm(`Revogar o token ${t.prefix}? Novas máquinas deixam de se matricular; as já matriculadas continuam.`)) void run(() => send("POST", `v1/enrollment-tokens/${t.id}/revoke`), "Token revogado."); };
  const revokeDevice = (id: string, host: string) => { if (confirm(`Revogar a máquina ${host}? Ela deixa de enviar eventos.`)) void run(() => send("POST", `v1/devices/${id}/revoke`), "Máquina revogada."); };

  const d = devices.data;
  const base = apiUrl.replace(/\/+$/, "");
  const winCmd = created ? `$env:PS_API='${base}'; $env:PS_TOKEN='${created.token}'; irm "$env:PS_API/sensor/install.ps1" | iex` : "";
  const unixCmd = created ? `curl -fsSL ${base}/sensor/install.sh | PS_API=${base} PS_TOKEN=${created.token} sh` : "";
  const command = created ? `promptshield-sensor.pyz deploy --api-url ${apiUrl} --token ${created.token} --confirm-employees-notified` : "";
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Dispositivos</h1>
        <p className="text-sm text-muted">Máquinas matriculadas e quais ferramentas elas vigiam. Cada máquina tem uma chave própria, revogável sozinha. Instalação em massa: EXPERIMENTAL, ainda não testada em MDM ou GPO reais (docs/implantacao-empresa.md).</p>
      </div>
      {devices.error && <ErrorBox message={devices.error} onRetry={devices.reload} />}
      {!d && !devices.error && <Loading />}
      {d && (
        <>
          <section aria-label="Licença" data-testid="license" className="rounded-md border border-line bg-panel p-4 text-sm">
            <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Licença</h2>
            {d.license.max_devices === null
              ? <p><strong>Sem limite de máquinas.</strong> {d.license.active_seats} ativas nos últimos {d.license.window_days} dias.</p>
              : (
                <>
                  <p><strong>{d.license.active_seats} de {d.license.max_devices}</strong> máquinas ativas nos últimos {d.license.window_days} dias.</p>
                  <progress className="mt-2 h-2 w-full" max={Math.max(d.license.max_devices, 1)} value={Math.min(d.license.active_seats, Math.max(d.license.max_devices, 1))} aria-label="Máquinas usadas da licença" />
                  {d.license.level === "alerta" && <p role="status" className="mt-2 text-med">Acima de 80% do limite: novas máquinas só entram enquanto houver vaga.</p>}
                  {d.license.level === "esgotada" && <p role="alert" className="mt-2 text-high">Limite atingido: novas máquinas não serão matriculadas. As já instaladas continuam enviando eventos. Revogue as que não são mais usadas ou fale com o fornecedor.</p>}
                </>
              )}
            {d.license.expired && <p role="alert" className="mt-2 text-high">Licença expirada: novas máquinas não podem ser matriculadas.</p>}
            {d.license.expires_at && !d.license.expired && <p className="mt-1 text-xs text-muted">Válida até {whenFull(d.license.expires_at)}.</p>}
            <p className="mt-2 text-xs text-muted">Uma máquina ocupa vaga se não foi revogada e enviou algo, ou foi matriculada, nos últimos {d.license.window_days} dias. Reinstalar na mesma máquina não gasta outra vaga. O limite é definido pelo fornecedor.</p>
          </section>
          <div className="grid gap-3 sm:grid-cols-3">
            <Kpi label="Máquinas ativas" value={d.active} />
            {Object.entries(d.coverage).map(([k, v]) => <Kpi key={k} label={TOOL_LABEL[k] ?? k} value={v} />)}
          </div>
          <Panel title="Máquinas">
            {d.devices.length === 0 ? <Empty>Nenhuma máquina matriculada.</Empty> : (
              <div className="overflow-x-auto"><table className="w-full min-w-[40rem] border-collapse" data-testid="devices-table">
                <caption className="sr-only">Máquinas matriculadas</caption>
                <thead><tr><th scope="col" className="th">Máquina</th><th scope="col" className="th">Sistema</th><th scope="col" className="th">Ferramentas</th><th scope="col" className="th">Matriculada</th><th scope="col" className="th">Último envio</th><th scope="col" className="th">Situação</th><th scope="col" className="th">Ocupa vaga</th><th scope="col" className="th"><span className="sr-only">Ações</span></th></tr></thead>
                <tbody>{d.devices.map((x) => (
                  <tr key={x.id} data-testid="device-row">
                    <th scope="row" className="td text-left font-medium">{x.hostname}</th><td className="td">{x.os ?? "—"}</td>
                    <td className="td text-xs">{x.tools.map((t) => TOOL_LABEL[t] ?? t).join(", ") || "—"}</td>
                    <td className="td text-xs">{whenFull(x.enrolled_at)}</td><td className="td text-xs">{x.last_seen_at ? whenFull(x.last_seen_at) : "nunca"}</td>
                    <td className="td">{x.revoked ? "revogada" : "ativa"}</td><td className="td text-xs">{x.counts_toward_license ? "sim" : "não"}</td>
                    <td className="td">{isAdmin && !x.revoked && <button type="button" className="btn" disabled={busy} onClick={() => revokeDevice(x.id, x.hostname)}>Revogar</button>}</td>
                  </tr>))}</tbody>
              </table></div>
            )}
          </Panel>
        </>
      )}
      <Panel title="Tokens de matrícula">
        {!isAdmin && <p className="text-sm text-muted">Só o administrador gerencia tokens.</p>}
        {isAdmin && (
          <>
            <form onSubmit={create} className="mb-3 flex flex-wrap items-end gap-3 text-sm">
              <div><label htmlFor="tname" className="mb-1 block font-medium">Nome (ex.: piloto TI)</label><input id="tname" required className="field" value={name} onChange={(e) => setName(e.target.value)} /></div>
              <div><label htmlFor="tdays" className="mb-1 block font-medium">Validade (dias)</label><input id="tdays" type="number" min={1} max={90} className="field w-24" value={days} onChange={(e) => setDays(Number(e.target.value))} /></div>
              <div><label htmlFor="tmax" className="mb-1 block font-medium">Máximo de máquinas</label><input id="tmax" type="number" min={1} max={100000} className="field w-28" value={maxUses} onChange={(e) => setMaxUses(Number(e.target.value))} /></div>
              <button className="btn" disabled={busy}>Criar token</button>
            </form>
            {tokens.data && (tokens.data.length === 0 ? <Empty>Nenhum token.</Empty> : (
              <div className="overflow-x-auto"><table className="w-full min-w-[36rem] border-collapse" data-testid="tokens-table">
                <caption className="sr-only">Tokens de matrícula</caption>
                <thead><tr><th scope="col" className="th">Nome</th><th scope="col" className="th">Prefixo</th><th scope="col" className="th">Situação</th><th scope="col" className="th">Usos</th><th scope="col" className="th">Expira</th><th scope="col" className="th"><span className="sr-only">Ações</span></th></tr></thead>
                <tbody>{tokens.data.map((t) => (
                  <tr key={t.id}><th scope="row" className="td text-left font-medium">{t.name}</th><td className="td font-mono text-xs">{t.prefix}</td><td className="td">{t.status}</td>
                    <td className="td">{t.uses}{t.max_uses ? ` / ${t.max_uses}` : ""}</td><td className="td text-xs">{whenFull(t.expires_at)}</td>
                    <td className="td">{t.status === "ativo" && <button type="button" className="btn" disabled={busy} onClick={() => revokeToken(t)}>Revogar</button>}</td></tr>))}</tbody>
              </table></div>
            ))}
          </>
        )}
      </Panel>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`text-sm ${msg.ok ? "" : "text-crit"}`}>{msg.text}</p>}
      <Dialog open={!!created} onClose={() => setCreated(null)} title="Token de matrícula criado">
        {created && (
          <div className="space-y-3 text-sm">
            <p>Copie agora: <strong>esta é a única vez</strong> que o token aparece. Ele só serve para matricular máquinas; cada máquina recebe uma chave própria.</p>
            <label htmlFor="apiurl" className="block font-medium">Endereço público da API (https)</label>
            <input id="apiurl" className="field w-full" value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} />
            <code className="block break-all rounded border border-line bg-panel2 p-2 font-mono text-xs" data-testid="new-token">{created.token}</code>
            <p className="font-medium">Instalar em uma máquina (uma linha, sem administrador). Windows, no PowerShell:</p>
            <code className="block break-all rounded border border-line bg-panel2 p-2 font-mono text-xs" data-testid="cmd-windows">{winCmd}</code>
            <p className="font-medium">Linux e macOS, no terminal:</p>
            <code className="block break-all rounded border border-line bg-panel2 p-2 font-mono text-xs" data-testid="cmd-unix">{unixCmd}</code>
            <p className="text-muted">Instala Claude Code e GitHub Copilot CLI, sem mais nada. Para incluir também a extensão do navegador (ChatGPT e Claude no site; exige um clique da pessoa no Chrome/Edge), acrescente <code>PS_TOOLS=claude_code,github_copilot_cli,browser_extension</code> antes do comando (no PowerShell: <code>$env:PS_TOOLS=&apos;claude_code,github_copilot_cli,browser_extension&apos;;</code>).</p>
            <p className="text-muted">O instalador mostra o que será enviado e pede a confirmação da pessoa (digitar &quot;sim&quot;). Precisa de Python 3.9 ou mais novo (no Windows ele tenta instalar com o winget). Por HTTP o script pode ser alterado por quem estiver no caminho: em produção use HTTPS.</p>
            <p>Para o TI, em nível de máquina (administrador, por MDM/GPO; exige o sensor já copiado):</p>
            <code className="block break-all rounded border border-line bg-panel2 p-2 font-mono text-xs" data-testid="deploy-command">{command}</code>
            <p className="text-muted">O argumento <code>--confirm-employees-notified</code> é a confirmação de que os empregados foram avisados do monitoramento: o aviso é obrigação da empresa.</p>
            <div className="flex justify-end"><button type="button" className="btn-primary" onClick={() => setCreated(null)}>Já guardei</button></div>
          </div>
        )}
      </Dialog>
    </div>
  );
}
