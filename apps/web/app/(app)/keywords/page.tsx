"use client";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Dialog } from "@/components/Dialog";
import { useSession } from "@/components/session";
import { Empty, ErrorBox, Loading, Panel } from "@/components/ui";
import { api, send, useLoad } from "@/lib/api";
import { whenFull } from "@/lib/format";
import type { KeywordRow } from "@/lib/types";

export default function KeywordsPage() {
  const { me } = useSession();
  const isAdmin = me.role === "admin";
  const rows = useLoad(() => api<KeywordRow[]>("v1/keywords"), []);
  const [term, setTerm] = useState("");
  const [score, setScore] = useState("");
  const [wholeWord, setWholeWord] = useState(false);
  const [fuzzy, setFuzzy] = useState(true);
  const [note, setNote] = useState("");
  const [edit, setEdit] = useState<{ row: KeywordRow; term: string; score: string; fuzzy: boolean; whole: boolean; note: string } | null>(null);
  const [editErr, setEditErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); rows.reload(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Falhou." }); } finally { setBusy(false); }
  }
  const body = (r: Pick<KeywordRow, "term" | "whole_word" | "fuzzy" | "score" | "note"> & { enabled: boolean }) => ({ term: r.term, whole_word: r.whole_word, fuzzy: r.fuzzy, score: r.score, enabled: r.enabled, note: r.note });
  const add = (ev: FormEvent) => {
    ev.preventDefault();
    const n = score.trim() === "" ? null : Number(score);
    if (n !== null && (!Number.isInteger(n) || n < 0 || n > 100)) { setMsg({ ok: false, text: "A pontuação deve ser um número inteiro de 0 a 100, ou ficar vazia." }); return; }
    void run(async () => { await send("POST", "v1/keywords", body({ term, whole_word: wholeWord, fuzzy, score: n, enabled: true, note: note.trim() || null })); setTerm(""); setScore(""); setNote(""); setWholeWord(false); setFuzzy(true); },
      "Palavra cadastrada. Vale para os próximos prompts.");
  };
  const toggle = (r: KeywordRow) => void run(() => send("PUT", `v1/keywords/${r.id}`, body({ ...r, enabled: !r.enabled })), r.enabled ? "Palavra desligada." : "Palavra ligada.");
  const openEdit = (r: KeywordRow) => { setEditErr(null); setEdit({ row: r, term: r.term, score: r.score === null ? "" : String(r.score), fuzzy: r.fuzzy, whole: r.whole_word, note: r.note ?? "" }); };
  async function saveEdit(ev: FormEvent) {
    ev.preventDefault();
    if (!edit) return;
    const n = edit.score.trim() === "" ? null : Number(edit.score);
    if (n !== null && (!Number.isInteger(n) || n < 0 || n > 100)) { setEditErr("A pontuação deve ser um número inteiro de 0 a 100, ou ficar vazia."); return; }
    setBusy(true);
    try {
      await send("PUT", `v1/keywords/${edit.row.id}`, body({ term: edit.term, whole_word: edit.whole, fuzzy: edit.fuzzy, score: n, enabled: edit.row.enabled, note: edit.note.trim() || null }));
      setEdit(null); setMsg({ ok: true, text: "Palavra atualizada. Vale para os próximos prompts." }); rows.reload();
    } catch (e) { setEditErr(e instanceof Error ? e.message : "Falhou."); } finally { setBusy(false); }
  }
  const remove = (r: KeywordRow) => { if (confirm(`Remover a palavra «${r.term}»? Os alertas já gerados continuam.`)) void run(() => send("DELETE", `v1/keywords/${r.id}`), "Palavra removida."); };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Palavras-chave</h1>
        <p className="text-sm text-muted">Cadastre uma palavra ou expressão: <strong>todo prompt que a contiver gera um alerta</strong> (veja em <Link href="/alerts" className="underline">Alertas e SIEM</Link>, regra «Palavra-chave monitorada»). A busca ignora maiúsculas e acentos e, por padrão, <strong>também pega palavras parecidas</strong> (erro de digitação, plural, letras trocadas; palavras de até 4 letras só casam exatas). Parecida é de <em>letras</em>, não de sentido: «carro» não pega «automóvel». Se você escolher uma pontuação, ela substitui a calculada pelo algoritmo naquele prompt; se deixar vazia, continua a calculada.</p>
      </div>
      <p role="note" className="rounded border border-line px-3 py-2 text-sm text-muted">
        O PromptShield é passivo: a palavra só gera alerta e pontuação, <strong>nunca bloqueia</strong> o prompt. O alerta guarda a palavra cadastrada, não o trecho do prompt. Vale para prompts novos; os anteriores não são reavaliados.
      </p>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`rounded border px-3 py-2 text-sm ${msg.ok ? "border-low bg-low-bg text-low" : "border-crit bg-crit-bg text-crit"}`}>{msg.text}</p>}
      {isAdmin && (
        <Panel title="Monitorar uma palavra">
          <form onSubmit={add} className="grid gap-3 md:grid-cols-2" aria-label="Monitorar uma palavra">
            <div><label htmlFor="kterm" className="block text-xs text-muted">Palavra ou expressão</label><input id="kterm" className="field w-full" required minLength={2} maxLength={100} placeholder="projeto fênix" value={term} onChange={(e) => setTerm(e.target.value)} /></div>
            <div><label htmlFor="kscore" className="block text-xs text-muted">Pontuação (0 a 100, opcional)</label><input id="kscore" className="field w-full" inputMode="numeric" placeholder="vazio = calculada pelo algoritmo" value={score} onChange={(e) => setScore(e.target.value)} /></div>
            <div><label htmlFor="knote" className="block text-xs text-muted">Por que (opcional)</label><input id="knote" className="field w-full" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} /></div>
            <div className="space-y-1 text-sm">
              <label className="block"><input type="checkbox" checked={fuzzy} onChange={(e) => setFuzzy(e.target.checked)} /> Aceitar palavras parecidas (erro de digitação, plural, letras trocadas)</label>
              <label className="block"><input type="checkbox" checked={wholeWord} onChange={(e) => setWholeWord(e.target.checked)} /> Só a palavra inteira (não dentro de outra palavra)</label>
            </div>
            <div><button type="submit" className="btn-primary" disabled={busy || term.trim().length < 2}>Monitorar</button></div>
          </form>
        </Panel>
      )}
      <Panel title="Palavras monitoradas">
        {rows.error && <ErrorBox message={rows.error} onRetry={rows.reload} />}
        {rows.loading && !rows.data && <Loading />}
        {rows.data && rows.data.length === 0 && <Empty>Nenhuma palavra cadastrada.</Empty>}
        {rows.data && rows.data.length > 0 && (
          <table className="w-full text-sm" data-testid="keywords-table">
            <thead><tr className="text-left text-xs text-muted"><th className="py-1">Palavra</th><th>Pontuação</th><th>Busca</th><th>Estado</th><th>Desde</th><th /></tr></thead>
            <tbody>
              {rows.data.map((r) => (
                <tr key={r.id} className="border-t border-line">
                  <td className="py-1 font-mono">{r.term}{r.note && <span className="block font-sans text-xs text-muted">{r.note}</span>}</td>
                  <td>{r.score === null ? "calculada" : r.score}</td>
                  <td>{r.whole_word ? "palavra inteira" : "contém"}{r.fuzzy ? " + parecidas" : ""}</td>
                  <td>{r.enabled ? "ligada" : "desligada"}</td>
                  <td>{whenFull(r.created_at)}</td>
                  <td className="space-x-2 text-right">{isAdmin && (<>
                    <button type="button" className="btn" disabled={busy} onClick={() => openEdit(r)} aria-label={`Editar ${r.term}`}>Editar</button>
                    <button type="button" className="btn" disabled={busy} onClick={() => toggle(r)} aria-label={`${r.enabled ? "Desligar" : "Ligar"} ${r.term}`}>{r.enabled ? "Desligar" : "Ligar"}</button>
                    <button type="button" className="btn" disabled={busy} onClick={() => remove(r)} aria-label={`Remover ${r.term}`}>Remover</button>
                  </>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    <Dialog open={!!edit} onClose={() => setEdit(null)} title="Editar palavra">
        {edit && (
          <form onSubmit={saveEdit} className="space-y-3 text-sm" aria-label="Editar palavra">
            <div><label htmlFor="eterm" className="block text-xs text-muted">Palavra ou expressão</label><input id="eterm" className="field w-full" required minLength={2} maxLength={100} value={edit.term} onChange={(e) => setEdit({ ...edit, term: e.target.value })} /></div>
            <div><label htmlFor="escore" className="block text-xs text-muted">Pontuação (0 a 100; vazio = calculada pelo algoritmo)</label><input id="escore" className="field w-full" inputMode="numeric" value={edit.score} onChange={(e) => setEdit({ ...edit, score: e.target.value })} /></div>
            <div><label htmlFor="enote" className="block text-xs text-muted">Por que (opcional)</label><input id="enote" className="field w-full" maxLength={300} value={edit.note} onChange={(e) => setEdit({ ...edit, note: e.target.value })} /></div>
            <label className="block"><input type="checkbox" checked={edit.fuzzy} onChange={(e) => setEdit({ ...edit, fuzzy: e.target.checked })} /> Aceitar palavras parecidas</label>
            <label className="block"><input type="checkbox" checked={edit.whole} onChange={(e) => setEdit({ ...edit, whole: e.target.checked })} /> Só a palavra inteira</label>
            {editErr && <p role="alert" className="rounded border border-crit bg-crit-bg px-3 py-2 text-crit">{editErr}</p>}
            <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={() => setEdit(null)}>Cancelar</button><button type="submit" className="btn-primary" disabled={busy || edit.term.trim().length < 2}>Salvar</button></div>
          </form>
        )}
      </Dialog>
    </div>
  );
}
