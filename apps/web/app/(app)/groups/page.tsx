"use client";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useSession } from "@/components/session";
import { Chip, Empty, ErrorBox, Loading, Panel } from "@/components/ui";
import { api, qs, send, useLoad } from "@/lib/api";
import { parseIds } from "@/lib/groups";
import type { PersonRow, UserGroup, UserGroupDetail } from "@/lib/types";

const CHUNK = 500;       // o servidor aceita até 500 pessoas por chamada

export default function GroupsPage() {
  const { me } = useSession();
  const isAdmin = me.role === "admin";
  const groups = useLoad(() => api<UserGroup[]>("v1/groups"), []);
  const [sel, setSel] = useState<string | null>(null);
  const detail = useLoad(() => (sel ? api<UserGroupDetail>(`v1/groups/${sel}`) : Promise.resolve(null)), [sel]);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [ids, setIds] = useState("");
  const [pq, setPq] = useState("");
  const [pqApplied, setPqApplied] = useState("");
  const [pmode, setPmode] = useState<"contains" | "prefix">("prefix");
  const [picked, setPicked] = useState<string[]>([]);
  const [mq, setMq] = useState("");
  useEffect(() => { const t = setTimeout(() => setPqApplied(pq.trim()), 250); return () => clearTimeout(t); }, [pq]);
  useEffect(() => { setPicked([]); setMq(""); }, [sel]);
  const found = useLoad(() => (sel && isAdmin ? api<PersonRow[]>(`v1/people${qs({ q: pqApplied || undefined, mode: pmode, days: 365, limit: 1000 })}`) : Promise.resolve(null)), [sel, isAdmin, pqApplied, pmode]);
  const members = useMemo(() => new Set(detail.data?.member_ids ?? []), [detail.data]);
  const candidates = (found.data ?? []).filter((x) => !members.has(x.user_id));       // quem já está no grupo não entra na seleção
  const togglePick = (u: string) => setPicked((c) => (c.includes(u) ? c.filter((x) => x !== u) : [...c, u]));
  const addPicked = () => {
    if (!sel || picked.length === 0) return;
    const list = picked;
    void run(async () => { for (let i = 0; i < list.length; i += CHUNK) await send("POST", `v1/groups/${sel}/members`, { user_ids: list.slice(i, i + CHUNK) }); setPicked([]); }, `${list.length} pessoa(s) adicionadas ao grupo.`);
  };
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); groups.reload(); detail.reload(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Falhou." }); } finally { setBusy(false); }
  }
  const create = (ev: FormEvent) => { ev.preventDefault(); void run(async () => { const g = await send<UserGroup>("POST", "v1/groups", { name, description: desc || null }); setName(""); setDesc(""); setSel(g.id); }, "Grupo criado."); };
  const add = (ev: FormEvent) => { ev.preventDefault(); const list = parseIds(ids); if (sel && list.length) void run(async () => { await send("POST", `v1/groups/${sel}/members`, { user_ids: list }); setIds(""); }, `${list.length} identificador(es) enviados.`); };
  const remove = (uid: string) => { if (sel && confirm(`Tirar ${uid} do grupo?`)) void run(() => send("POST", `v1/groups/${sel}/members/remove`, { user_ids: [uid] }), "Pessoa removida do grupo."); };   // corpo, não caminho: o e-mail tem @ e pontos
  const del = (g: UserGroup) => { if (confirm(`Apagar o grupo ${g.name}?`)) void run(async () => { await send("DELETE", `v1/groups/${g.id}`); setSel(null); }, "Grupo apagado."); };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Grupos de usuários</h1>
        <p className="text-sm text-muted">Agrupe pessoas para aplicar políticas e exceções. Escolha as pessoas na lista (quem já apareceu nos prompts) ou digite o identificador que o sensor envia. Quem pertence a um grupo é decidido aqui, no servidor: um sensor não consegue se declarar de um grupo. O nome do grupo não muda depois de criado, porque as políticas se referem a ele.</p>
      </div>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`rounded border px-3 py-2 text-sm ${msg.ok ? "border-low bg-low-bg text-low" : "border-crit bg-crit-bg text-crit"}`}>{msg.text}</p>}
      {groups.error && <ErrorBox message={groups.error} onRetry={groups.reload} />}
      {groups.loading && !groups.data && <Loading />}
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Grupos">
          {groups.data && groups.data.length === 0 && <Empty>Nenhum grupo ainda.</Empty>}
          {groups.data && groups.data.length > 0 && (
            <table className="w-full text-sm" data-testid="groups-table">
              <thead><tr className="text-left text-xs text-muted"><th className="py-1">Nome</th><th>Membros</th><th /></tr></thead>
              <tbody>
                {groups.data.map((g) => (
                  <tr key={g.id} className="border-t border-line">
                    <td className="py-1"><strong>{g.name}</strong>{g.description && <div className="text-xs text-muted">{g.description}</div>}</td>
                    <td>{g.members}</td>
                    <td className="space-x-2 text-right">
                      <button type="button" className="btn" onClick={() => setSel(g.id)} aria-pressed={sel === g.id}>Abrir</button>
                      {isAdmin && <button type="button" className="btn" disabled={busy} onClick={() => del(g)}>Apagar</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {isAdmin && (
            <form onSubmit={create} className="mt-4 grid gap-2 border-t border-line pt-3" aria-label="Novo grupo">
              <div><label htmlFor="gname" className="block text-xs text-muted">Nome do grupo</label><input id="gname" className="field w-full" required maxLength={60} value={name} onChange={(e) => setName(e.target.value)} /></div>
              <div><label htmlFor="gdesc" className="block text-xs text-muted">Descrição (opcional)</label><input id="gdesc" className="field w-full" maxLength={300} value={desc} onChange={(e) => setDesc(e.target.value)} /></div>
              <div><button type="submit" className="btn-primary" disabled={busy || !name.trim()}>Criar grupo</button></div>
            </form>
          )}
        </Panel>
        <Panel title={detail.data ? `Membros de ${detail.data.name}` : "Membros"}>
          {!sel && <Empty>Abra um grupo para ver e editar os membros.</Empty>}
          {detail.error && <ErrorBox message={detail.error} onRetry={detail.reload} />}
          {detail.data && (
            <>
              {detail.data.member_ids.length > 8 && (
                <div className="mb-2"><label htmlFor="mq" className="block text-xs text-muted">Filtrar membros</label><input id="mq" className="field w-full" value={mq} onChange={(e) => setMq(e.target.value)} placeholder="parte do identificador" /></div>
              )}
              {detail.data.member_ids.length === 0 ? <Empty>Grupo sem membros.</Empty> : (
                <ul className="max-h-72 divide-y divide-line overflow-auto text-sm" data-testid="members">
                  {detail.data.member_ids.filter((u) => !mq.trim() || u.toLowerCase().includes(mq.trim().toLowerCase())).map((u) => (
                    <li key={u} className="flex items-center justify-between py-1"><span className="font-mono">{u}</span>
                      {isAdmin && <button type="button" className="btn" disabled={busy} onClick={() => remove(u)} aria-label={`Tirar ${u} do grupo`}>Tirar</button>}
                    </li>
                  ))}
                </ul>
              )}
              {isAdmin && (
                <section className="mt-4 space-y-2 border-t border-line pt-3" aria-label="Escolher pessoas para o grupo" data-testid="picker">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Escolher pessoas (quem já usou IA no último ano)</h3>
                  <div className="grid gap-2 sm:grid-cols-[minmax(0,2fr)_1fr]">
                    <div><label htmlFor="pq" className="block text-xs text-muted">Procurar</label><input id="pq" className="field w-full" maxLength={100} value={pq} onChange={(e) => setPq(e.target.value)} placeholder="ex.: DTC-" /></div>
                    <div><label htmlFor="pmode" className="block text-xs text-muted">Como procurar</label>
                      <select id="pmode" className="field w-full" value={pmode} onChange={(e) => setPmode(e.target.value as "contains" | "prefix")}><option value="prefix">Começa com</option><option value="contains">Contém</option></select></div>
                  </div>
                  {found.error && <ErrorBox message={found.error} onRetry={found.reload} />}
                  {found.loading && !found.data && <Loading />}
                  {found.data && (candidates.length === 0 ? <Empty>{found.data.length === 0 ? "Ninguém encontrado." : "Todas as pessoas encontradas já estão no grupo."}</Empty> : (
                    <>
                      <div className="flex flex-wrap items-center gap-2 text-sm">
                        <button type="button" className="btn" onClick={() => setPicked(candidates.map((x) => x.user_id))}>Selecionar todos os resultados ({candidates.length}{found.data.length === 1000 ? "+" : ""})</button>
                        <button type="button" className="btn" onClick={() => setPicked([])} disabled={picked.length === 0}>Limpar seleção</button>
                      </div>
                      <ul className="max-h-64 divide-y divide-line overflow-auto rounded border border-line text-sm" data-testid="candidates">
                        {candidates.map((x) => (
                          <li key={x.user_id}><label className="flex cursor-pointer items-center gap-2 px-2 py-1 hover:bg-panel2">
                            <input type="checkbox" checked={picked.includes(x.user_id)} onChange={() => togglePick(x.user_id)} />
                            <span className="font-mono">{x.user_id}</span><span className="text-xs text-muted">{x.department ?? "sem departamento"}</span>
                            {(x.groups ?? []).map((g) => <Chip key={g}>{g}</Chip>)}
                          </label></li>
                        ))}
                      </ul>
                    </>
                  ))}
                  <div><button type="button" className="btn-primary" disabled={busy || picked.length === 0} onClick={addPicked}>Adicionar selecionados ({picked.length})</button></div>
                </section>
              )}
              {isAdmin && (
                <details className="mt-3 border-t border-line pt-2">
                  <summary className="cursor-pointer text-xs text-muted">Adicionar digitando os identificadores (para quem ainda não apareceu nos prompts)</summary>
                <form onSubmit={add} className="mt-2 grid gap-2" aria-label="Adicionar membros">
                  <div><label htmlFor="mids" className="block text-xs text-muted">Identificadores (um por linha, ou separados por vírgula)</label>
                    <textarea id="mids" className="field w-full font-mono" rows={4} value={ids} onChange={(e) => setIds(e.target.value)} /></div>
                  <div><button type="submit" className="btn-primary" disabled={busy || parseIds(ids).length === 0}>Adicionar</button></div>
                </form>
                </details>
              )}
            </>
          )}
        </Panel>
      </div>
      {!isAdmin && <p className="text-xs text-muted">Só administradores alteram grupos.</p>}
    </div>
  );
}
