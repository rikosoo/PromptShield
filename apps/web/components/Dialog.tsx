"use client";
import { useEffect, useRef, type ReactNode } from "react";

/** <dialog> nativo: foco preso, Esc fecha, e o foco volta ao botão que abriu. */
export function Dialog({ open, onClose, title, children, wide = false }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="dlg-title"
      className={`m-auto w-[calc(100%-2rem)] rounded-lg border border-line bg-panel p-0 text-fg backdrop:bg-black/50 ${wide ? "max-w-3xl" : "max-w-lg"}`}>
      {open && (
        <div className="p-5">
          <h2 id="dlg-title" className="mb-3 text-lg font-bold">{title}</h2>
          {children}
        </div>
      )}
    </dialog>
  );
}
