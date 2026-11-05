"""Catálogo das IAs que o administrador pode escolher monitorar, com o estado HONESTO de cada uma e o passo a passo.

Estados: AUTOMÁTICO (o sensor configura sozinho), EXTENSÃO (o sensor prepara; falta um clique no navegador), MANUAL (instruções que o sensor
não aplica porque o formato não foi verificado) e INDISPONÍVEL (não há como monitorar com o que existe hoje). Nada é prometido além disso."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

AUTO, EXT, MANUAL, NONE = "automatico", "extensao", "manual", "indisponivel"
TAG = {AUTO: "automático", EXT: "extensão", MANUAL: "manual, a verificar", NONE: "indisponível hoje"}


def tag(i: "IA") -> str:
    """Estado honesto em uma expressão: "extensão, testado" (viu funcionar numa máquina real) ou "..., experimental"."""
    return f"{TAG[i.state]}, {'testado' if i.tested else 'experimental'}" if i.state in (AUTO, EXT) else TAG[i.state]

EXT_STEPS = [
    "O sensor baixa a extensão e a deixa pronta em ~/.promptshield/extension (no Windows, %USERPROFILE%\\.promptshield\\extension), já com a chave desta máquina.",
    "No navegador, abra chrome://extensions (Edge: edge://extensions) e ligue o 'Modo do desenvolvedor'.",
    "Clique em 'Carregar sem compactação' e escolha a pasta acima (só na primeira vez; a mesma extensão serve para todos os sites da lista).",
    "Abra o site e recarregue (F5): deve aparecer 'PromptShield: monitoramento ativo'. Se o aviso disser que o monitoramento pode estar inativo, o site mudou o HTML: avise para ajustarmos o seletor.",
]


@dataclass(frozen=True)
class IA:
    n: int
    name: str
    state: str
    tool: str | None            # ferramenta do sensor que a cobre (claude_code, github_copilot_cli, browser_extension) ou None
    status: str                 # uma frase honesta
    steps: list[str] = field(default_factory=list)
    tested: bool = False        # True só quando o dono viu a captura funcionar numa máquina real; não é promessa de que continua funcionando


CATALOG: list[IA] = [
    IA(1, "ChatGPT (web, chatgpt.com)", EXT, "browser_extension",
       "Extensão do navegador. TESTADA: prompts reais de chatgpt.com apareceram no console no teste do dono (2026-11-04). PARCIAL: os seletores dependem do HTML do site e podem mudar sem aviso.", EXT_STEPS, tested=True),
    IA(2, "Copilot (web, copilot.com)", EXT, "browser_extension",
       "Extensão do navegador. EXPERIMENTAL: campo e botão de enviar conferidos no HTML real de copilot.com/chat (2026-11-04); falta teste de ponta a ponta. Cobre copilot.com e copilot.microsoft.com; não cobre o GitHub Copilot em github.com/copilot nem o Microsoft 365 Copilot.",
       EXT_STEPS),
    IA(3, "Gemini (web, gemini.google.com)", EXT, "browser_extension",
       "Extensão do navegador. TESTADA: prompts reais de gemini.google.com apareceram no console no teste do dono (2026-11-04). PARCIAL: os seletores dependem do HTML do site e podem mudar sem aviso.", EXT_STEPS, tested=True),
    IA(4, "Claude (web, claude.ai)", EXT, "browser_extension",
       "Extensão do navegador. EXPERIMENTAL: seletores nunca conferidos na página real (A VERIFICAR).", EXT_STEPS),
    IA(5, "Claude Code (CLI, terminal)", AUTO, "claude_code",
       "Hooks no ~/.claude/settings.json. É a integração mais testada (PARCIAL: testada no Claude Code real, com lacunas listadas em docs/claude-code-hooks.md).",
       ["O sensor grava os hooks no settings.json do usuário (com cópia de segurança) e a chave desta máquina em ~/.promptshield/hook.json.",
        "Feche e abra de novo as sessões do Claude Code já abertas; depois use normalmente.",
        "Teste: mande 'SIMULADO: o CPF de teste é 529.982.247-25' e veja o evento em Análise de prompts.",
        "Se o CLI mostrar 'Hook failed' ou nada aparecer no console: rode `python <sensor.pyz> doctor`. Ele roda o hook como o CLI roda, com um texto sintético, e mostra o código de saída e a causa.",
        "Para remover: python <sensor.pyz> deploy --user --uninstall --confirm-employees-notified."], tested=True),
    IA(6, "Codex (CLI)", AUTO, "codex_cli",
       "Hooks de usuário em ~/.codex/hooks.json (formato conferido na documentação de Hooks do Codex, cópia colada em 2026-11-04). EXPERIMENTAL: no primeiro teste real (Windows, 2026-11-05) o hook saiu com código 1 (\"Hook failed\") e nada foi enviado; o comando agora vale em cmd, PowerShell e sh, o hook sempre sai com 0 e registra a causa, mas ainda não foi visto enviando no Codex real. O nome do campo do prompt é A VERIFICAR (aceitamos vários e registramos os campos recebidos).",
       ["O sensor acrescenta os hooks do PromptShield ao ~/.codex/hooks.json (com cópia de segurança; os seus hooks não são tocados).",
        "O Codex EXIGE que você revise e confie nos hooks novos: abra o Codex CLI e digite /hooks, confie nos do PromptShield. Sem isso eles ficam parados.",
        "Teste: mande 'SIMULADO: o CPF de teste é 529.982.247-25' e veja o evento (ferramenta codex_cli) em Análise de prompts.",
        "Se o CLI mostrar 'Hook failed' ou nada aparecer no console: rode `python <sensor.pyz> doctor`. Ele roda o hook como o CLI roda, com um texto sintético, e mostra o código de saída e a causa.",
        "Para remover: python <sensor.pyz> deploy --user --uninstall --confirm-employees-notified."]),
    IA(7, "GitHub Copilot CLI (terminal)", AUTO, "github_copilot_cli",
       "Hooks de usuário em ~/.copilot/hooks/promptshield.json. EXPERIMENTAL: só testado com entradas simuladas. O prompt só é monitorado (o Copilot descarta a resposta); ações de ferramenta podem ser negadas.",
       ["O sensor grava só o arquivo ~/.copilot/hooks/promptshield.json (nada mais é alterado).",
        "Abra uma nova sessão do Copilot CLI e mande um prompt sintético.",
        "Se o CLI mostrar 'Hook failed' ou nada aparecer no console: rode `python <sensor.pyz> doctor`. Ele roda o hook como o CLI roda, com um texto sintético, e mostra o código de saída e a causa.",
        "Não cobre o Copilot dentro do VS Code nem as sugestões em linha."]),
]
BY_N = {i.n: i for i in CATALOG}
# identificador estável de cada IA (vai para o servidor; o console mostra o nome). Onde a IA gera eventos, é o mesmo valor de `source.app`.
KEY = {1: "chatgpt_web", 2: "copilot_web", 3: "gemini_web", 4: "claude_web", 5: "claude_code", 6: "codex_cli", 7: "github_copilot_cli"}
ALL_TOOLS_FROM = {"claude_code", "github_copilot_cli", "browser_extension"}


def render_list() -> str:
    lines = ["Quais IAs você quer monitorar?"]
    for i in CATALOG:
        lines.append(f"  {i.n}) {i.name}   [{tag(i)}]")
    lines.append("Digite os números separados por vírgula (ex.: 1,3,5), ou 'todas'.")
    return "\n".join(lines)


def parse_selection(text: str) -> tuple[list[int], list[str]]:
    """'1, 2 ,6' | '1;2' | 'todas' -> ([1, 2, 6], erros). Remove repetidos, mantém a ordem numérica."""
    t = (text or "").strip().lower()
    if t in ("todas", "todos", "all", "*"):
        return [i.n for i in CATALOG], []
    if not t:
        return [], ["nenhum número informado"]
    if re.search(r"[^0-9,;\s]", t):
        return [], [f"use só números separados por vírgula (recebi: {text.strip()!r})"]
    nums = sorted({int(x) for x in re.findall(r"\d+", t)})
    bad = [str(n) for n in nums if n not in BY_N]
    if bad:
        return [], [f"número fora da lista: {', '.join(bad)} (use de 1 a {len(CATALOG)})"]
    return nums, []


def tools_for(nums: list[int]) -> list[str]:
    """Ferramentas do sensor que cobrem a seleção, sem repetir e em ordem estável."""
    out: list[str] = []
    for n in nums:
        t = BY_N[n].tool
        if t and t not in out:
            out.append(t)
    return out


def keys_for(nums: list[int]) -> list[str]:
    """Identificadores das IAs escolhidas, na ordem dos números."""
    return [KEY[n] for n in nums]


def guide(n: int, command: str = "") -> str:
    i = BY_N[n]
    head = f"[{n}] {i.name}: {tag(i).upper()}\n  {i.status}"
    steps = "\n".join(f"  {k}. {s.replace('{COMMAND}', command or '<python> <caminho do sensor.pyz>')}" for k, s in enumerate(i.steps, 1))
    return f"{head}\n{steps}" if steps else head
