"use client";
import { useEffect, useState, type FormEvent } from "react";
import { canTriage, useSession } from "@/components/session";
import { ErrorBox } from "@/components/ui";
import { send } from "@/lib/api";

/** Ver o texto ORIGINAL de um prompt: só se a empresa guarda o original (cifrado), só administrador e analista, com justificativa e registro na auditoria. */
export function OriginalViewer({ eventId, hasOriginal }: { eventId: string; hasOriginal: boolean }) {
  const { me } = useSession();
  const [asking, setAsking] = useState(false);
  const [why, setWhy] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  useEffect(() => { setAsking(false); setWhy(""); setErr(null); setText(null); }, [eventId]);   // outro prompt: nada do anterior fica na tela

  async function reveal(ev: FormEvent) {
    ev.preventDefault();
    setErr(null);
    try {
      const r = await send<{ text: string }>("POST", `v1/events/${eventId}/original`, { justification: why });
      setText(r.text);
      setAsking(false);
      setWhy("");
    } catch (e) { setErr(e instanceof Error ? e.message : "Erro"); }
  }

  if (!hasOriginal) return <p className="text-xs text-muted" data-testid="no-original">O texto original não foi guardado para este prompt. Para ver o prompt completo nos próximos, o administrador liga <strong>«Guardar também o texto original»</strong> em Privacidade e segurança (fica cifrado, com justificativa e auditoria).</p>;
  if (!canTriage(me.role)) return <p className="text-xs text-muted">Só administrador e analista podem pedir o texto original.</p>;
  return (
    <div className="space-y-2">
      {text === null && !asking && <button type="button" className="btn" onClick={() => setAsking(true)}>Ver texto original</button>}
      {asking && (
        <form onSubmit={reveal} className="space-y-2 rounded border border-line p-3" aria-label="Pedir o texto original">
          <p className="text-xs text-muted">O texto original contém o que a plataforma mascara por padrão. Informe o motivo: fica registrado na auditoria com o seu nome.</p>
          <label htmlFor="orig-why" className="block text-xs font-medium">Justificativa (mínimo de 10 caracteres)</label>
          <textarea id="orig-why" required minLength={10} rows={2} className="field w-full" value={why} onChange={(e) => setWhy(e.target.value)} />
          {err && <ErrorBox message={err} />}
          <div className="flex gap-2"><button type="submit" className="btn-primary" disabled={why.trim().length < 10}>Ver texto original</button>
            <button type="button" className="btn" onClick={() => setAsking(false)}>Cancelar</button></div>
        </form>
      )}
      {text !== null && (
        <div className="rounded border border-crit bg-crit-bg p-3" role="region" aria-label="Texto original">
          <p className="mb-1 text-xs font-semibold text-crit">Texto original. Este acesso foi registrado na auditoria.</p>
          <pre className="whitespace-pre-wrap break-words font-mono text-sm text-fg" data-testid="original">{text}</pre>
          <button type="button" className="btn mt-2" onClick={() => setText(null)}>Esconder</button>
        </div>
      )}
    </div>
  );
}
