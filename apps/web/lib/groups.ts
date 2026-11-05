/** Separa identificadores por linha, vírgula ou ponto e vírgula; tira vazios e repetidos (a ordem da primeira aparição se mantém). */
export function parseIds(raw: string): string[] {
  return [...new Set(raw.split(/[\n,;]+/).map((x) => x.trim()).filter(Boolean))];
}
