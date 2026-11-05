const fmt = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const fmtFull = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "medium" });
const fmtDay = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", timeZone: "UTC" });

export const when = (iso: string) => fmt.format(new Date(iso));
export const whenFull = (iso: string) => fmtFull.format(new Date(iso));
export const dayLabel = (isoDate: string) => fmtDay.format(new Date(isoDate + "T00:00:00Z"));
export const pct = (v: number) => `${Math.round(v * 100)}%`;

/** Parte o texto mascarado em trechos, marcando as máscaras (***.***.***-25, [CPF], AKIA****...). */
const MASK = /(\*{2,}[\w.\-*/@]*|[\w.\-]*\*{2,}[\w.\-*]*|\[(?:CPF|CNPJ|RG|nome|endereço|oculto|comando|trecho suspeito|caracteres ocultos|conta bancária)\])/g;
export function splitMasks(text: string): { text: string; mask: boolean }[] {
  const out: { text: string; mask: boolean }[] = [];
  let last = 0;
  for (const m of text.matchAll(MASK)) {
    if (m.index > last) out.push({ text: text.slice(last, m.index), mask: false });
    out.push({ text: m[0], mask: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), mask: false });
  return out;
}

export const clip = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
