"use client";
import { useEffect, useState } from "react";
import { Dialog } from "@/components/Dialog";
import { useSession } from "@/components/session";
import { Empty, ErrorBox, Kpi, Loading, Panel } from "@/components/ui";
import { api, qs, send, useLoad } from "@/lib/api";
import { whenFull } from "@/lib/format";
import { EVIDENCE_LABEL, filterSensors, IA_INFO, iaLabel, iaState, latestVersion, MODE_LABEL, PROBLEM_LABEL, problemCounts, problems, sensorStatus, STATUS_LABEL, summarize, type ProblemCode, type SensorSort, type SensorStatus } from "@/lib/sensors";
import type { DeviceRow, DevicesOut } from "@/lib/types";

const TOOL_LABEL: Record<string, string> = { claude_code: "Hook do Claude Code", github_copilot_cli: "Hook do GitHub Copilot CLI", browser_extension: "Extensão do navegador" };

function IaChip({ d, id }: { d: DeviceRow; id: string }) {
  const s = iaState(d, id);
  const strong = s.evidence === "capturando";
  return (
    <li className={`mb-1 mr-1 inline-block rounded border px-1.5 py-0.5 text-xs ${strong ? "border-low bg-low-bg text-low" : "border-line bg-panel2 text-muted"}`} data-testid="ia-chip">
      <span className="font-medium">{s.label}</span> <span>· {strong ? "capturando" : s.evidence === "aguardando" ? "aguardando evento" : s.evidence === "parou" ? "sem eventos há 7 dias+" : s.evidence === "manual" ? "manual" : "indisponível"}</span>
    </li>
  );
}

export default function SensorsPage() {
  const { me } = useSession();
  const isAdmin = me.role === "admin";
  const canExport = me.role === "admin" || me.role === "auditor";
  const data = useLoad(() => api<DevicesOut>("v1/devices"), []);
  const [q, setQ] = useState("");
  const [ia, setIa] = useState("");
  const [status, setStatus] = useState<SensorStatus | "">("");
  const [problem, setProblem] = useState<ProblemCode | "qualquer" | "">("");
  const [sort, setSort] = useState<SensorSort>("hostname");
  const [live, setLive] = useState(false);
  const [open, setOpen] = useState<DeviceRow | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => { setNow(new Date()); }, [data.data]);
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => data.reload(), 30000);          // atualização automática, só enquanto marcada
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live]);

  const d = data.data;
  const all = d?.devices ?? [];
  const sum = summarize(all, now);
  const rows = filterSensors(all, { q, ia, status, problem }, now, sort);
  const latest = latestVersion(all);
  const pc = problemCounts(all, now);
  const exportHref = `/api/proxy/v1/devices/export.csv${qs({ q: q.trim(), ia, situacao: status })}`;
  const iaIds = [...new Set([...Object.keys(IA_INFO), ...all.flatMap((x) => x.ias ?? [])])];
  const cover = d?.ias_coverage ?? {};
  const selected = open ? (all.find((x) => x.id === open.id) ?? open) : null;

  async function revoke(x: DeviceRow) {
    if (!confirm(`Revogar a máquina ${x.hostname}? Ela deixa de enviar eventos.`)) return;
    setBusy(true); setMsg(null);
    try { await send("POST", `v1/devices/${x.id}/revoke`); setMsg({ ok: true, text: "Máquina revogada." }); setOpen(null); data.reload(); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Falhou." }); } finally { setBusy(false); }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold">Sensores</h1>
          <p className="text-sm text-muted">Todas as máquinas com sensor instalado, o nome da máquina e quais IAs foram habilitadas em cada uma. &quot;Capturando&quot; só aparece quando chegou evento de verdade. O sensor só fala com o servidor quando alguém usa uma IA: <strong>sem atividade não quer dizer que quebrou</strong>.</p>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> Atualizar sozinho a cada 30 s</label>
      </div>
      {data.error && <ErrorBox message={data.error} onRetry={data.reload} />}
      {data.loading && !d && <Loading />}
      {d && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" data-testid="sensor-kpis">
            <Kpi label="Sensores instalados" value={sum.total} hint="sem contar os revogados" />
            <Kpi label="Ativos nas últimas 24 h" value={sum.ativo} />
            <Kpi label="Sem atividade há 1 a 7 dias" value={sum.quieto} />
            <Kpi label="Inativos há mais de 7 dias" value={sum.inativo + sum.nunca} hint={sum.nunca ? `${sum.nunca} nunca enviaram` : undefined} />
            <Kpi label="Revogados" value={sum.revogado} />
          </div>
          <Panel title="IAs habilitadas (clique para filtrar)">
            <ul className="flex flex-wrap gap-1" data-testid="ia-coverage">
              {iaIds.filter((id) => (cover[id] ?? 0) > 0 || ia === id).map((id) => (
                <li key={id}>
                  <button type="button" aria-pressed={ia === id} onClick={() => setIa(ia === id ? "" : id)}
                    className={`rounded border px-2 py-1 text-xs ${ia === id ? "border-accent bg-accent text-accent-fg" : "border-line bg-panel hover:bg-panel2"}`}>
                    {iaLabel(id)} <span className="font-mono">{cover[id] ?? 0}</span>
                  </button>
                </li>
              ))}
              {Object.keys(cover).length === 0 && <li className="text-xs text-muted">Nenhum sensor informou as IAs escolhidas ainda.</li>}
            </ul>
            {sum.semIas > 0 && <p className="mt-2 text-xs text-muted" data-testid="sem-ias">{sum.semIas} sensor(es) não informaram as IAs (instalados sem escolher IAs, ou com versão antiga do sensor). Neles aparece só o mecanismo instalado (hook ou extensão).</p>}
          </Panel>
          <Panel title={`Precisam de atenção (${pc.total})`}>
            {pc.total === 0 ? <p className="text-sm" data-testid="sem-alertas">Nenhum sensor com alerta agora.</p> : (
              <ul className="flex flex-wrap gap-1" data-testid="alertas">
                {(Object.keys(PROBLEM_LABEL) as ProblemCode[]).filter((c) => pc.byCode[c] > 0).map((c) => (
                  <li key={c}>
                    <button type="button" aria-pressed={problem === c} onClick={() => setProblem(problem === c ? "" : c)}
                      className={`rounded border px-2 py-1 text-xs ${problem === c ? "border-accent bg-accent text-accent-fg" : "border-line bg-panel hover:bg-panel2"}`}>
                      {PROBLEM_LABEL[c]} <span className="font-mono">{pc.byCode[c]}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-xs text-muted">Alertas são pistas, não provas: o sensor só fala quando alguém usa uma IA, então máquina parada pode estar só sem uso.</p>
          </Panel>
          <form className="flex flex-wrap items-end gap-3 rounded-md border border-line bg-panel px-4 py-3 text-sm" onSubmit={(e) => e.preventDefault()}>
            <div><label htmlFor="q" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Nome da máquina</label>
              <input id="q" className="field w-56" value={q} maxLength={100} onChange={(e) => setQ(e.target.value)} placeholder="ex.: NOTE-ANA" /></div>
            <div><label htmlFor="ia" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">IA habilitada</label>
              <select id="ia" className="field" value={ia} onChange={(e) => setIa(e.target.value)}>
                <option value="">Todas</option>{iaIds.map((id) => <option key={id} value={id}>{iaLabel(id)}</option>)}</select></div>
            <div><label htmlFor="st" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Situação</label>
              <select id="st" className="field" value={status} onChange={(e) => setStatus(e.target.value as SensorStatus | "")}>
                <option value="">Todas</option>{(Object.keys(STATUS_LABEL) as SensorStatus[]).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}</select></div>
            <div><label htmlFor="so" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Ordenar por</label>
              <select id="so" className="field" value={sort} onChange={(e) => setSort(e.target.value as SensorSort)}>
                <option value="hostname">Nome da máquina</option><option value="recente">Último envio</option></select></div>
            <div><label htmlFor="pr" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Alertas</label>
              <select id="pr" className="field" value={problem} onChange={(e) => setProblem(e.target.value as ProblemCode | "qualquer" | "")}>
                <option value="">Todos os sensores</option><option value="qualquer">Com qualquer alerta</option>
                {(Object.keys(PROBLEM_LABEL) as ProblemCode[]).map((c) => <option key={c} value={c}>{PROBLEM_LABEL[c]}</option>)}</select></div>
            {(q || ia || status || problem) && <button type="button" className="btn" onClick={() => { setQ(""); setIa(""); setStatus(""); setProblem(""); }}>Limpar filtros</button>}
            {canExport && <a className="btn ml-auto" data-testid="export-sensors" download href={exportHref}>Exportar CSV (auditado)</a>}
          </form>
          <Panel title={`Sensores (${rows.length} de ${all.length})`}>
            {rows.length === 0 ? <Empty>{all.length === 0 ? "Nenhum sensor instalado ainda. Crie um token em Dispositivos e rode a linha de instalação." : "Nenhum sensor com esses filtros."}</Empty> : (
              <div className="relative overflow-x-auto">
                <table className="w-full min-w-[64rem] border-collapse" data-testid="sensors-table">
                  <caption className="sr-only">Sensores instalados, com as IAs habilitadas em cada um</caption>
                  <thead><tr>
                    <th scope="col" className="th">Nome da máquina</th><th scope="col" className="th">Sistema</th><th scope="col" className="th">Último usuário</th><th scope="col" className="th">IAs habilitadas</th>
                    <th scope="col" className="th">Último envio</th><th scope="col" className="th">Situação</th><th scope="col" className="th">Sensor</th>
                  </tr></thead>
                  <tbody>{rows.map((x) => {
                    const st = sensorStatus(x, now);
                    return (
                      <tr key={x.id} data-testid="sensor-row">
                        <th scope="row" className="td text-left font-medium"><button type="button" className="text-accent underline-offset-2 hover:underline" onClick={() => setOpen(x)} aria-label={`Ver detalhes da máquina ${x.hostname}`}>{x.hostname}</button></th>
                        <td className="td">{x.os ?? "—"}</td>
                        <td className="td text-xs" data-testid="last-user">{x.last_user ? <>{x.last_user}{(x.users_30d ?? 0) > 1 && <span className="text-muted"> · +{(x.users_30d ?? 1) - 1} pessoa(s) em 30 dias</span>}</> : <span className="text-muted">sem eventos em 30 dias</span>}</td>
                        <td className="td">{(x.ias ?? []).length ? <ul className="flex flex-wrap" aria-label={`IAs habilitadas em ${x.hostname}`}>{(x.ias ?? []).map((id) => <IaChip key={id} d={x} id={id} />)}</ul>
                          : <span className="text-xs text-muted">não informado{x.tools.length ? ` · ${x.tools.map((t) => TOOL_LABEL[t] ?? t).join(", ")}` : ""}</span>}</td>
                        <td className="td whitespace-nowrap text-xs">{x.last_seen_at ? whenFull(x.last_seen_at) : "nunca"}</td>
                        <td className="td text-xs">{STATUS_LABEL[st]}{problems(x, now, latest).length > 0 && <ul className="mt-1" aria-label={`Alertas de ${x.hostname}`}>{problems(x, now, latest).map((p) => <li key={p.code} className="text-high" data-testid="alerta">⚠ {PROBLEM_LABEL[p.code]}</li>)}</ul>}</td>
                        <td className="td text-xs">{x.client_version ?? "—"}{latest && x.client_version && !x.revoked && problems(x, now, latest).some((p) => p.code === "versao") && <span className="block text-high">desatualizado</span>}</td>
                      </tr>
                    );
                  })}</tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}
      {msg && <p role={msg.ok ? "status" : "alert"} className={`text-sm ${msg.ok ? "" : "text-crit"}`}>{msg.text}</p>}
      <Dialog open={!!selected} onClose={() => setOpen(null)} title={selected ? `Sensor ${selected.hostname}` : "Sensor"} wide>
        {selected && (
          <div className="space-y-3 text-sm" data-testid="sensor-detail">
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
              <dt className="text-muted">Nome da máquina</dt><dd className="font-medium">{selected.hostname}</dd>
              <dt className="text-muted">Sistema</dt><dd>{selected.os ?? "—"}</dd>
              <dt className="text-muted">Versão do sensor</dt><dd>{selected.client_version ?? "—"}</dd>
              <dt className="text-muted">Matriculada em</dt><dd>{whenFull(selected.enrolled_at)}</dd>
              <dt className="text-muted">Último envio</dt><dd>{selected.last_seen_at ? whenFull(selected.last_seen_at) : "nunca"}</dd>
              <dt className="text-muted">Situação</dt><dd>{STATUS_LABEL[sensorStatus(selected, now)]}</dd>
              <dt className="text-muted">Último usuário</dt><dd>{selected.last_user ? `${selected.last_user}${selected.last_department ? ` (${selected.last_department})` : ""}${selected.last_user_at ? `, em ${whenFull(selected.last_user_at)}` : ""}` : "sem eventos em 30 dias"}</dd>
              <dt className="text-muted">Pessoas em 30 dias</dt><dd>{selected.users_30d ?? 0}{(selected.users_30d ?? 0) > 1 ? " (máquina compartilhada?)" : ""}</dd>
              <dt className="text-muted">Mecanismos instalados</dt><dd>{selected.tools.map((t) => TOOL_LABEL[t] ?? t).join(", ") || "—"}</dd>
              <dt className="text-muted">Ocupa vaga da licença</dt><dd>{selected.counts_toward_license ? "sim" : "não"}</dd>
            </dl>
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase text-muted">IAs habilitadas nesta máquina</h3>
              {(selected.ias ?? []).length === 0 ? <p className="text-xs text-muted">O sensor não informou as IAs. Rode o assistente de configuração do sensor (<code>setup</code>) e escolha as IAs, ou reinstale com <code>--ias</code>.</p> : (
                <div className="relative overflow-x-auto"><table className="w-full min-w-[34rem] border-collapse" data-testid="ia-detail">
                  <caption className="sr-only">IAs habilitadas e eventos recebidos</caption>
                  <thead><tr><th scope="col" className="th">IA</th><th scope="col" className="th">Como é monitorada</th><th scope="col" className="th">Situação</th><th scope="col" className="th">Eventos 7 dias</th><th scope="col" className="th">Eventos 30 dias</th><th scope="col" className="th">Último evento</th></tr></thead>
                  <tbody>{(selected.ias ?? []).map((id) => {
                    const s = iaState(selected, id);
                    return <tr key={id}><th scope="row" className="td text-left font-medium">{s.label}</th><td className="td text-xs">{MODE_LABEL[s.mode]}</td><td className="td text-xs">{EVIDENCE_LABEL[s.evidence]}</td>
                      <td className="td font-mono">{s.events7d}</td><td className="td font-mono">{s.events30d}</td><td className="td text-xs">{s.lastAt ? whenFull(s.lastAt) : "—"}</td></tr>;
                  })}</tbody>
                </table></div>
              )}
              <p className="mt-2 text-xs text-muted">Extensão do navegador: o sensor só deixa a extensão pronta; a pessoa ainda precisa carregá-la uma vez. Por isso &quot;aguardando evento&quot; pode significar que ainda falta esse clique. Itens manuais ou indisponíveis não geram evidência.</p>
            </div>
            {problems(selected, now, latest).length > 0 && (
              <div role="group" aria-label="Alertas desta máquina"><h3 className="mb-1 text-xs font-semibold uppercase text-muted">Alertas</h3>
                <ul className="space-y-1 text-xs" data-testid="detail-alertas">{problems(selected, now, latest).map((p) => <li key={p.code}>⚠ {p.text}</li>)}</ul></div>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <a className="btn" href={`/history?sensor=${encodeURIComponent(selected.id)}&host=${encodeURIComponent(selected.hostname)}`} data-testid="ver-prompts">Ver os prompts deste sensor</a>
              {isAdmin && !selected.revoked && <button type="button" className="btn" disabled={busy} onClick={() => void revoke(selected)}>Revogar</button>}
              <button type="button" className="btn" onClick={() => setOpen(null)}>Fechar</button>
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}
