"use client";
import { useState, type FormEvent } from "react";
import { Dialog } from "@/components/Dialog";
import { useSession } from "@/components/session";
import { Chip, Empty, ErrorBox, Loading, Panel } from "@/components/ui";
import { api, send, useLoad } from "@/lib/api";
import { whenFull } from "@/lib/format";
import { ROLE_CAN, ROLE_LABEL } from "@/lib/labels";
import { passwordOk, passwordRules } from "@/lib/password";
import type { Collaborator } from "@/lib/types";

type Role = Collaborator["role"];
const ROLES = Object.keys(ROLE_LABEL) as Role[];

/** Colaboradores: quem tem acesso ao console e com qual função. */
export default function CollaboratorsPage() {
  const { me } = useSession();
  const isAdmin = me.role === "admin";
  const rows = useLoad(() => (isAdmin ? api<Collaborator[]>("v1/users") : Promise.resolve([] as Collaborator[])), [isAdmin]);
  const localAuth = !!me.local_auth;
  const [temp, setTemp] = useState<{ email: string; password: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [form, setForm] = useState({ email: "", name: "", role: "leitura" as Role, department: "", active: true, password: "" });
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
    if (form.password && !passwordOk(form.password)) { setMsg({ ok: false, text: "A senha inicial não cumpre a política (veja os requisitos abaixo do campo)." }); return; }
    const email = form.email.trim();
    void run(async () => {
      const r = await send<{ temporary_password?: string }>("POST", "v1/users", { email, display_name: form.name.trim() || null, role: form.role, department: form.department.trim() || null, active: form.active, ...(form.password ? { password: form.password } : {}) });
      setForm({ email: "", name: "", role: "leitura", department: "", active: true, password: "" });
      if (r.temporary_password) { setCopied(false); setTemp({ email, password: r.temporary_password }); }
    }, localAuth ? "Colaborador cadastrado. Ele entra com o e-mail e a senha e é obrigado a trocá-la no primeiro acesso." : "Colaborador cadastrado. Ele entra com o login da empresa usando este e-mail.");
  };
  const toggle = (r: Collaborator) => void run(() => send("PATCH", `v1/users/${r.id}`, { active: !r.active }), r.active ? "Acesso desativado: a pessoa não entra mais." : "Acesso reativado.");
  const resetPassword = (r: Collaborator) => {
    if (!confirm(`Gerar uma senha temporária para ${r.email}? A senha atual deixa de valer e as sessões abertas dele são encerradas.`)) return;
    void run(async () => { const x = await send<{ temporary_password: string }>("POST", `v1/users/${r.id}/password`); setCopied(false); setTemp({ email: r.email, password: x.temporary_password }); }, "Senha temporária gerada.");
  };
  async function copy() { try { await navigator.clipboard.writeText(temp!.password); setCopied(true); } catch { setCopied(false); } }
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
              {localAuth && (
                <div className="md:col-span-2"><label htmlFor="cpass" className="block text-xs text-muted">Senha inicial (opcional: vazia, o sistema gera uma temporária e mostra uma vez)</label>
                  <input id="cpass" type="password" autoComplete="new-password" maxLength={128} className="field w-full md:w-1/2" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} aria-describedby="crules" />
                  {form.password && <ul id="crules" className="mt-1 space-y-0.5 text-xs">{passwordRules(form.password).map((x) => <li key={x.id} className={x.ok ? "text-low" : "text-muted"}><span aria-hidden="true">{x.ok ? "✓" : "○"}</span> {x.label}</li>)}</ul>}
                  <p className="mt-1 text-xs text-muted">Em qualquer caso, a pessoa é obrigada a trocar a senha no primeiro acesso.</p></div>
              )}
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
                        <td className="td">{r.active ? "Ativo" : <span className="text-high">Desativado</span>}
                          {localAuth && <div className="text-xs text-muted">{!r.has_password ? "sem senha (não entra)" : r.must_change_password ? "senha provisória: troca pendente" : "senha definida"}{r.locked && <span className="ml-1 text-high">· bloqueado por tentativas</span>}</div>}</td>
                        <td className="td whitespace-nowrap font-mono text-xs">{whenFull(r.created_at)}</td>
                        <td className="td space-x-2 whitespace-nowrap text-right">
                          <button type="button" className="btn" disabled={busy} onClick={() => openEdit(r)} aria-label={`Editar ${r.email}`}>Editar</button>
                          {localAuth && !r.is_me && <button type="button" className="btn" disabled={busy} onClick={() => resetPassword(r)} aria-label={`Nova senha temporária para ${r.email}`}>Nova senha</button>}
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
      <Dialog open={!!temp} onClose={() => setTemp(null)} title="Senha temporária" confirmClose="Esta senha aparece só agora. Já copiou e passou para a pessoa?">
        {temp && (
          <div className="space-y-3 text-sm" data-testid="temp-password">
            <p>Passe esta senha para <strong>{temp.email}</strong> por um canal seguro. Ela <strong>não será mostrada de novo</strong>, e a pessoa é obrigada a trocá-la ao entrar.</p>
            <p className="rounded border border-line bg-panel2 p-3 font-mono text-base" data-testid="temp-password-value">{temp.password}</p>
            <div className="flex flex-wrap items-center justify-end gap-2">
              {copied && <span role="status" className="text-xs text-low">Copiada.</span>}
              <button type="button" className="btn" onClick={() => void copy()}>Copiar</button>
              <button type="button" className="btn-primary" onClick={() => setTemp(null)}>Já anotei</button>
            </div>
          </div>
        )}
      </Dialog>
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
