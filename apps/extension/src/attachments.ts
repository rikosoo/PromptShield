/**
 * Arquivos que o usuário anexa na página. Guarda SÓ nome, tamanho e tipo (nunca lê o conteúdo do arquivo).
 * Limites honestos: se o usuário remover o arquivo na página antes de enviar, a extensão não percebe; o nome seguirá junto do
 * próximo envio. Fica registrado o que foi ANEXADO, não necessariamente o que foi enviado.
 */
export interface FileInfo {
  name: string;
  size: number;
  type: string;
}

export const MAX_FILES = 20;

export function infoOf(files: ArrayLike<{ name: string; size: number; type: string }> | null | undefined): FileInfo[] {
  if (!files) return [];
  return Array.from(files, (f) => ({ name: String(f.name).slice(0, 255), size: Number(f.size) || 0, type: String(f.type || "").slice(0, 100) })).filter((f) => f.name);
}

export function createTracker() {
  let items: FileInfo[] = [];
  return {
    add(files: FileInfo[]): void {
      for (const f of files) {
        if (items.length >= MAX_FILES) break;
        if (!items.some((x) => x.name === f.name && x.size === f.size)) items.push(f);
      }
    },
    list: (): FileInfo[] => items.slice(),
    clear(): void { items = []; },
  };
}
