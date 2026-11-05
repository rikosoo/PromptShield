"use client";
import { useEffect, useRef, type ReactNode } from "react";

/**
 * <dialog> nativo: foco preso, Esc fecha, e o foco volta ao botão que abriu.
 * Também fecha pelo botão X e clicando fora da janela (o clique só conta se começou e terminou no fundo:
 * selecionar texto e soltar o mouse fora NÃO fecha).
 * `confirmClose`: para janelas que mostram algo uma única vez (token, chave). Pergunta antes de fechar, por X, clique fora ou Esc.
 */
export function Dialog({ open, onClose, title, children, wide = false, confirmClose }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean; confirmClose?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const downOnBackdrop = useRef(false);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  /** O clique caiu fora da caixa da janela (no fundo escurecido)? Por coordenadas: a barra de rolagem da própria janela também tem `target` igual ao <dialog>. */
  const outside = (e: { clientX: number; clientY: number }) => {
    const r = ref.current?.getBoundingClientRect();
    return !!r && (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom);
  };
  const requestClose = () => {
    if (confirmClose && !window.confirm(confirmClose)) return;
    ref.current?.close();        // dispara o evento close nativo, que chama onClose
  };
  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="dlg-title"
      onCancel={(e) => { if (confirmClose && !window.confirm(confirmClose)) e.preventDefault(); }}
      onMouseDown={(e) => { downOnBackdrop.current = outside(e); }}
      onClick={(e) => { if (downOnBackdrop.current && outside(e)) requestClose(); downOnBackdrop.current = false; }}
      className={`m-auto w-[calc(100%-2rem)] rounded-lg border border-line bg-panel p-0 text-fg backdrop:bg-black/50 ${wide ? "max-w-3xl" : "max-w-lg"}`}>
      {open && (
        <div className="p-5">
          <div className="mb-3 flex items-start justify-between gap-3">
            <h2 id="dlg-title" className="text-lg font-bold">{title}</h2>
            <button type="button" onClick={requestClose} aria-label="Fechar" title="Fechar (Esc)"
              className="-mr-1 -mt-1 shrink-0 rounded-md border border-line bg-panel px-2 py-1 text-base leading-none text-fg hover:bg-panel2">
              <span aria-hidden="true">✕</span>
            </button>
          </div>
          {children}
        </div>
      )}
    </dialog>
  );
}
