"use client";
import { useState, type FormEvent } from "react";
import { useSession } from "@/components/session";
import { Empty, ErrorBox, Loading, Panel } from "@/components/ui";
import { api, send, useLoad } from "@/lib/api";
import { whenFull } from "@/lib/format";
import { REPORT_KIND_LABEL } from "@/lib/labels";
import type { ReportRow, ScheduleRow } from "@/lib/types";

const iso = (d: Date) => d.toISOString().slice(0, 10);
function lastMonth(): [string, string] {
  const now = new Date();
  return [iso(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1))), iso(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 0)))];
}

export default function ReportsPage() {
  const { me } = useSession();
  const isAdmin = me.role === "admin";
  const list = useLoad(() => api<ReportRow[]>("v1/reports"), []);
  const sched = useLoad(() => api<ScheduleRow[]>("v1/reports/schedules"), []);
  const [start0, end0] = lastMonth();
  const [f, setF] = useState({ kind: "executivo", format: "pdf", start: start0, end: end0 });
  const [s, setS] = useState({ kind: "executivo", format: "pdf", frequency: "mensal", recipients: "" });
  const [err, setErr] = useState<string | null>(null);
  const [serr, setSerr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function generate(ev: FormEvent) {
    ev.preventDefault();
    setBusy(true);
    setErr(null);
    try { await send("POST", "v1/reports", f); list.reload(); } catch (e) { setErr(e instanceof Error ? e.message : "Erro"); } finally { setBusy(false); }
  }
  async function schedule(ev: FormEvent) {
    ev.preventDefault();
    setSerr(null);
    try {
      await send("POST", "v1/reports/schedules", { ...s, recipients: s.recipients.split(",").map((x) => x.trim()).filter(Boolean) });
      sched.reload();
    } catch (e) { setSerr(e instanceof Error ? e.message : "Erro"); }
  }
  async function removeSchedule(id: string) { await send("DELETE", `v1/reports/schedules/${id}`); sched.reload(); }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Relatórios</h1>
      <p className="max-w-3xl text-sm text-muted">Os relatórios usam as mesmas consultas do painel, então os totais conferem. São agregados: não trazem texto de prompt. O relatório LGPD é um <strong>modelo</strong> e precisa de revisão jurídica.</p>
      <Panel title="Gerar agora">
        <form onSubmit={generate} className="flex flex-wrap items-end gap-3 text-sm">
          <div><label htmlFor="rk" className="mb-1 block font-medium">Relatório</label>
            <select id="rk" className="field" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="executivo">Executivo</option><option value="lgpd">Conformidade LGPD</option><option value="piloto">Final do piloto</option></select></div>
          <div><label htmlFor="rf" className="mb-1 block font-medium">Formato</label>
            <select id="rf" className="field" value={f.format} onChange={(e) => setF({ ...f, format: e.target.value })}><option value="pdf">PDF</option><option value="csv">CSV</option></select></div>
          <div><label htmlFor="rs" className="mb-1 block font-medium">De</label><input id="rs" type="date" required className="field" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></div>
          <div><label htmlFor="re" className="mb-1 block font-medium">Até</label><input id="re" type="date" required className="field" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></div>
          <button className="btn-primary" disabled={busy}>Gerar</button>
        </form>
        {err && <p role="alert" className="mt-2 text-sm text-crit">{err}</p>}
      </Panel>
      <Panel title="Relatórios gerados">
        {list.error && <ErrorBox message={list.error} onRetry={list.reload} />}
        {list.loading && !list.data && <Loading />}
        {list.data && (list.data.length === 0 ? <Empty>Nenhum relatório gerado ainda.</Empty> : (
          <div className="overflow-x-auto"><table className="w-full min-w-[40rem] border-collapse" data-testid="reports-table">
            <caption className="sr-only">Relatórios gerados</caption>
            <thead><tr><th scope="col" className="th">Relatório</th><th scope="col" className="th">Período</th><th scope="col" className="th">Gerado</th><th scope="col" className="th"><span className="sr-only">Baixar</span></th></tr></thead>
            <tbody>{list.data.map((r) => (
              <tr key={r.id} data-testid="report-row">
                <th scope="row" className="td text-left font-medium">{REPORT_KIND_LABEL[r.kind]} ({r.format.toUpperCase()}){r.scheduled && <span className="ml-2 text-xs text-muted">agendado</span>}</th>
                <td className="td font-mono text-xs">{r.period_start} a {r.period_end}</td>
                <td className="td text-xs">{whenFull(r.created_at)} · {r.created_by}</td>
                <td className="td"><a className="text-accent underline" href={`/api/proxy/v1/reports/${r.id}/download`} download>Baixar {r.format.toUpperCase()}</a></td>
              </tr>))}</tbody>
          </table></div>
        ))}
      </Panel>
      <Panel title="Agendamento">
        {sched.data && sched.data.length > 0 && (
          <ul className="mb-3 space-y-1 text-sm" data-testid="schedules">{sched.data.map((x) => (
            <li key={x.id} className="flex flex-wrap items-center gap-2">
              <span>{REPORT_KIND_LABEL[x.kind]} · {x.format.toUpperCase()} · {x.frequency}{x.recipients.length ? ` · ${x.recipients.join(", ")}` : " · sem e-mail (só guarda)"}{x.last_period_end ? ` · último período ${x.last_period_end}` : ""}</span>
              {isAdmin && <button type="button" className="btn" onClick={() => removeSchedule(x.id)}>Remover</button>}
            </li>))}</ul>
        )}
        {isAdmin ? (
          <form onSubmit={schedule} className="flex flex-wrap items-end gap-3 text-sm">
            <div><label htmlFor="sk" className="mb-1 block font-medium">Relatório</label>
              <select id="sk" className="field" value={s.kind} onChange={(e) => setS({ ...s, kind: e.target.value })}><option value="executivo">Executivo</option><option value="lgpd">Conformidade LGPD</option><option value="piloto">Final do piloto</option></select></div>
            <div><label htmlFor="sf" className="mb-1 block font-medium">Formato</label>
              <select id="sf" className="field" value={s.format} onChange={(e) => setS({ ...s, format: e.target.value })}><option value="pdf">PDF</option><option value="csv">CSV</option></select></div>
            <div><label htmlFor="sq" className="mb-1 block font-medium">Frequência</label>
              <select id="sq" className="field" value={s.frequency} onChange={(e) => setS({ ...s, frequency: e.target.value })}><option value="mensal">Mensal</option><option value="semanal">Semanal</option></select></div>
            <div className="min-w-[14rem] flex-1"><label htmlFor="sr" className="mb-1 block font-medium">E-mails (separe por vírgula; opcional)</label><input id="sr" className="field w-full" value={s.recipients} onChange={(e) => setS({ ...s, recipients: e.target.value })} /></div>
            <button className="btn">Agendar</button>
          </form>
        ) : <p className="text-sm text-muted">Só o administrador agenda relatórios.</p>}
        {serr && <p role="alert" className="mt-2 text-sm text-crit">{serr}</p>}
        <p className="mt-3 text-xs text-muted">Os agendamentos são executados pelo worker (<code>python -m app.worker</code>), que gera o último período completo uma única vez. O envio por e-mail exige SMTP configurado.</p>
      </Panel>
    </div>
  );
}
