"use client";
import { useState, type FormEvent } from "react";
import { Dialog } from "@/components/Dialog";
import { useSession } from "@/components/session";
import { Chip, Empty, ErrorBox, Loading, Panel } from "@/components/ui";
import { api, send, useLoad } from "@/lib/api";
import { whenFull } from "@/lib/format";
import { ROLE_CAN, ROLE_LABEL } from "@/lib/labels";
import type { Collaborator } from "@/lib/types";

type Role = Collaborator["role"];
const ROLES = Object.keys(ROLE_LABEL) as Role[];

/** Colaboradores: quem tem acesso ao console e com qual função. */
export default function CollaboratorsPage() {
  const { me } = useSession();
  const isAdmin = me.role === "admin";
  const rows = useLoad(() => (isAdmin ? api<Collaborator[]>("v1/users") : Promise.resolve([] as Collaborator[])), [isAdmin]);
  const [form, setForm] = useState({ email: "", name: "", role: "leitura" as Role, department: "", active: true });
  const [edit, setEdit] = useState<{ row: Collaborator; name: string; role: Role; department: string } | null>(null);
  const [editErr, setEditErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>, ok: string): Promise<boolean> {
    setBusy(true);
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); rows.reload(); return true; }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Falhou." }); return false; }
    finally { setBusy(false); }
  }
  const add = (ev: FormEvent) => {
    ev.preventDefault();
    void run(async () => {
      await send("POST", "v1/users", { email: form.email.trim(), display_name: form.name.trim() || null, role: form.role, department: form.department.trim() || null, active: form.active });
      setForm({ email: "", name: "", role: "leitura", department: "", active: true });
    }, "Colaborador cadastrado. Ele entra com o login da empresa usando este e-mail.");
  };
  const toggle = (r: Collaborator) => void run(() => send("PATCH", `v1/users/${r.id}`, { active: !r.active }), r.active ? "Acesso desativado: a pessoa não entra mais." : "Acesso reativado.");
  const remove = (r: Collaborator) => { if (confirm(`Remover ${r.email}? A pessoa perde o acesso. O registro de auditoria guarda só o identificador interno.`)) void run(() => send("DELETE", `v1/users/${r.id}`), "Colaborador removido."); };
  const openEdit = (r: Collaborator) => { setEditErr(null); setEdit({ row: r, name: r.display_name ?? "", role: r.role, department: r.department ?? "" }); };
  async function saveEdit(ev: FormEvent) {
    ev.preventDefault();
    if (!edit) return;
    setBusy(true);
    try {
      await send("PATCH", `v1/users/${edit.row.id}`, { display_name: edit.name.trim() || null, role: edit.role, department: edit.department.trim() || null });
      setEdit(null); setMsg({ ok: true, text: "Colaborador atualizado." }); rows.reload();
    } catch (e) { setEditErr(e instanceof Error ? e.message : "Falhou."); } finally { setBusy(false); }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Colaboradores</h1>
        <p className="max-w-3xl text-sm text-muted">Quem tem acesso a <strong>este console</strong> e com qual função. Não são as pessoas monitoradas (essas estão em <em>Usuários</em>). Quem entra é só quem está nesta lista e ativo; o login é pelo e-mail cadastrado, e o sistema não envia convite por e-mail.</p>
      </div>
      <Panel title="O que cada função pode">
        <dl className="grid gap-2 text-sm md:grid-cols-2" data-testid="roles-help">
          {ROLES.map((r) => <div key={r}><dt className="font-semibold">{ROLE_LABEL[r]}</dt><dd className="text-muted">{ROLE_CAN[r]}</dd></div>)}
        </dl>
      </Panel>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`rounded border px-3 py-2 text-sm ${msg.ok ? "border-low bg-low-bg text-low" : "border-crit bg-crit-bg text-crit"}`}>{msg.text}</p>}
      {!isAdmin && <Panel><Empty>Só administradores veem e alteram a lista de colaboradores.</Empty></Panel>}
      {isAdmin && (
        <>
          <Panel title="Adicionar colaborador">
            <form onSubmit={add} className="grid gap-3 md:grid-cols-2" aria-label="Adicionar colaborador">
              <div><label htmlFor="cemail" className="block text-xs text-muted">E-mail de login</label><input id="cemail" type="email" required maxLength={320} className="field w-full" placeholder="nome@empresa.com.br" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
              <div><label htmlFor="cname" className="block text-xs text-muted">Nome (opcional)</label><input id="cname" className="field w-full" maxLength={200} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
              <div><label htmlFor="crole" className="block text-xs text-muted">Função</label>
                <select id="crole" className="field w-full" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>{ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select>
                <p className="mt-1 text-xs text-muted">{ROLE_CAN[form.role]}</p></div>
              <div><label htmlFor="cdept" className="block text-xs text-muted">Departamento (opcional)</label><input id="cdept" className="field w-full" maxLength={120} value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} />
                <label className="mt-3 block text-sm"><input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> Acesso ativo</label></div>
              <div><button type="submit" className="btn-primary" disabled={busy || !form.email.trim()}>Adicionar</button></div>
            </form>
          </Panel>
          <Panel title={`Quem tem acesso (${rows.data?.length ?? 0})`}>
            {rows.error && <ErrorBox message={rows.error} onRetry={rows.reload} />}
            {rows.loading && !rows.data && <Loading />}
            {rows.data && rows.data.length === 0 && <Empty>Nenhum colaborador.</Empty>}
            {rows.data && rows.data.length > 0 && (
              <div className="relative overflow-x-auto">
                <table className="w-full min-w-[44rem] border-collapse" data-testid="collab-table">
                  <caption className="sr-only">Colaboradores com acesso ao console</caption>
                  <thead><tr><th scope="col" className="th">Colaborador</th><th scope="col" className="th">Função</th><th scope="col" className="th">Departamento</th><th scope="col" className="th">Acesso</th><th scope="col" className="th">Desde</th><th scope="col" className="th"><span className="sr-only">Ações</span></th></tr></thead>
                  <tbody>
                    {rows.data.map((r) => (
                      <tr key={r.id} data-testid="collab-row">
                        <th scope="row" className="td text-left font-normal"><div className="font-medium">{r.display_name ?? r.email}{r.is_me && <span className="ml-2"><Chip>você</Chip></span>}</div>{r.display_name && <div className="text-xs text-muted">{r.email}</div>}</th>
                        <td className="td">{ROLE_LABEL[r.role]}</td>
                        <td className="td">{r.department ?? "—"}</td>
                        <td className="td">{r.active ? "Ativo" : <span className="text-high">Desativado</span>}</td>
                        <td className="td whitespace-nowrap font-mono text-xs">{whenFull(r.created_at)}</td>
                        <td className="td space-x-2 whitespace-nowrap text-right">
                          <button type="button" className="btn" disabled={busy} onClick={() => openEdit(r)} aria-label={`Editar ${r.email}`}>Editar</button>
                          <button type="button" className="btn" disabled={busy} onClick={() => toggle(r)} aria-label={`${r.active ? "Desativar" : "Reativar"} ${r.email}`}>{r.active ? "Desativar" : "Reativar"}</button>
                          <button type="button" className="btn" disabled={busy || r.is_me} onClick={() => remove(r)} aria-label={`Remover ${r.email}`} title={r.is_me ? "Você não pode remover a si mesmo" : undefined}>Remover</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}
      <Dialog open={!!edit} onClose={() => setEdit(null)} title="Editar colaborador">
        {edit && (
          <form onSubmit={saveEdit} className="space-y-3 text-sm" aria-label="Editar colaborador">
            <p className="text-muted">E-mail (não muda): <span className="font-mono">{edit.row.email}</span></p>
            <div><label htmlFor="ename" className="block text-xs text-muted">Nome</label><input id="ename" className="field w-full" maxLength={200} value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></div>
            <div><label htmlFor="erole" className="block text-xs text-muted">Função</label>
              <select id="erole" className="field w-full" value={edit.role} onChange={(e) => setEdit({ ...edit, role: e.target.value as Role })}>{ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select>
              <p className="mt-1 text-xs text-muted">{ROLE_CAN[edit.role]}</p></div>
            <div><label htmlFor="edept" className="block text-xs text-muted">Departamento</label><input id="edept" className="field w-full" maxLength={120} value={edit.department} onChange={(e) => setEdit({ ...edit, department: e.target.value })} /></div>
            {editErr && <p role="alert" className="rounded border border-crit bg-crit-bg px-3 py-2 text-crit">{editErr}</p>}
            <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={() => setEdit(null)}>Cancelar</button><button type="submit" className="btn-primary" disabled={busy}>Salvar</button></div>
          </form>
        )}
      </Dialog>
    </div>
  );
}
