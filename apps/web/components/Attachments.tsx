import { fileSize } from "@/lib/format";
import type { PromptRow } from "@/lib/types";

/** Arquivos anexados ao prompt: só o nome (já mascarado), o tamanho e o tipo. O conteúdo do arquivo nunca é coletado. */
export function Attachments({ row, compact = false }: { row: Pick<PromptRow, "attachments">; compact?: boolean }) {
  const list = row.attachments ?? [];
  if (!list.length) return null;
  return (
    <ul className={compact ? "mt-1 flex flex-wrap gap-1" : "space-y-1 font-mono text-xs"} data-testid="attachments" aria-label="Arquivos anexados">
      {list.map((a, i) => (
        <li key={i} className={compact ? "rounded border border-line px-1 text-xs" : ""}>
          <span aria-hidden="true">📎 </span>{a.name}{a.size != null && <span className="text-muted"> · {fileSize(a.size)}</span>}
        </li>
      ))}
    </ul>
  );
}
