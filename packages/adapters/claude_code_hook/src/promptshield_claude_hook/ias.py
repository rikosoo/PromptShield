"""Catálogo das IAs que o administrador pode escolher monitorar, com o estado HONESTO de cada uma e o passo a passo.

Estados: AUTOMÁTICO (o sensor configura sozinho), EXTENSÃO (o sensor prepara; falta um clique no navegador), MANUAL (instruções que o sensor
não aplica porque o formato não foi verificado) e INDISPONÍVEL (não há como monitorar com o que existe hoje). Nada é prometido além disso."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

AUTO, EXT, MANUAL, NONE = "automatico", "extensao", "manual", "indisponivel"
TAG = {AUTO: "automático", EXT: "extensão, experimental", MANUAL: "manual, a verificar", NONE: "indisponível hoje"}

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


CATALOG: list[IA] = [
    IA(1, "ChatGPT (web, chatgpt.com)", EXT, "browser_extension",
       "Extensão do navegador. EXPERIMENTAL: o seu teste manual em chatgpt.com capturou prompts; os seletores podem mudar sem aviso.", EXT_STEPS),
    IA(2, "Copilot (web, copilot.com)", EXT, "browser_extension",
       "Extensão do navegador. EXPERIMENTAL: campo e botão de enviar conferidos no HTML real de copilot.com/chat (2026-11-04); falta teste de ponta a ponta. Cobre copilot.com e copilot.microsoft.com; não cobre o GitHub Copilot em github.com/copilot nem o Microsoft 365 Copilot.",
       EXT_STEPS),
    IA(3, "Gemini (web, gemini.google.com)", EXT, "browser_extension",
       "Extensão do navegador. EXPERIMENTAL: seletores nunca conferidos na página real (A VERIFICAR).", EXT_STEPS),
    IA(4, "Codex (app desktop)", NONE, None,
       "Sem hooks documentados para o app desktop do Codex nas fontes que consegui ler. A VERIFICAR.",
       ["O motor de hooks do Codex está documentado no Codex CLI (item 7). Se o app desktop usar a mesma configuração do CLI, o vínculo do item 7 poderia valer: NÃO está confirmado.",
        "Teste, se quiser: faça o item 7, abra o app desktop, mande um prompt sintético e veja se o evento aparece em Análise de prompts. Se não aparecer, o app não passa pelos hooks.",
        "Sem isso, o app desktop do Codex não é monitorado (só um agente de desktop ou proxy veria o conteúdo, e ambos estão fora do escopo do projeto)."]),
    IA(5, "Claude (app desktop)", MANUAL, "claude_code",
       "Aba Code: usa os mesmos arquivos de configuração do Claude Code, mas o disparo dos hooks lá está A VERIFICAR. O chat comum NÃO tem hooks.",
       ["Marque também o item 6: o vínculo é o mesmo (hooks no settings.json do usuário), e a documentação diz que o app desktop lê os mesmos arquivos de configuração do CLI.",
        "Teste: abra o app, aba Code, mande 'SIMULADO: o CPF de teste é 529.982.247-25' e veja se o evento aparece. Se aparecer, a aba Code está coberta.",
        "O chat comum do app e o Cowork não têm hooks e não são cobertos. Para empresa com Claude Enterprise, o caminho é o inference hook (docs/inference-hooks.md), ainda não testado com um tenant real.",
        "Alternativa para conversar: usar claude.ai no navegador com a extensão (item 10)."]),
    IA(6, "Claude Code (CLI, terminal)", AUTO, "claude_code",
       "Hooks no ~/.claude/settings.json. É a integração mais testada (PARCIAL: testada no Claude Code real, com lacunas listadas em docs/claude-code-hooks.md).",
       ["O sensor grava os hooks no settings.json do usuário (com cópia de segurança) e a chave desta máquina em ~/.promptshield/hook.json.",
        "Feche e abra de novo as sessões do Claude Code já abertas; depois use normalmente.",
        "Teste: mande 'SIMULADO: o CPF de teste é 529.982.247-25' e veja o evento em Análise de prompts.",
        "Para remover: python <sensor.pyz> deploy --user --uninstall --confirm-employees-notified."]),
    IA(7, "Codex (CLI)", AUTO, "codex_cli",
       "Hooks de usuário em ~/.codex/hooks.json (formato conferido na documentação de Hooks do Codex, cópia colada em 2026-11-04). EXPERIMENTAL: nunca rodou no Codex real; o nome do campo do prompt no UserPromptSubmit é A VERIFICAR.",
       ["O sensor acrescenta os hooks do PromptShield ao ~/.codex/hooks.json (com cópia de segurança; os seus hooks não são tocados).",
        "O Codex EXIGE que você revise e confie nos hooks novos: abra o Codex CLI e digite /hooks, confie nos do PromptShield. Sem isso eles ficam parados.",
        "Teste: mande 'SIMULADO: o CPF de teste é 529.982.247-25' e veja o evento (ferramenta codex_cli) em Análise de prompts.",
        "Para remover: python <sensor.pyz> deploy --user --uninstall --confirm-employees-notified."]),
    IA(8, "Copilot (app desktop)", NONE, None,
       "Microsoft 365 Copilot: só por API do servidor (Microsoft Graph), conector NÃO construído. O Copilot gratuito do Windows: sem nenhum gancho que eu tenha encontrado.",
       ["Microsoft 365 Copilot da empresa: a API getAllEnterpriseInteractions da Microsoft Graph lista as interações (exige licença do Copilot, permissão AiEnterpriseInteraction.Read.All consentida pelo administrador do tenant e não oferece consulta incremental). O conector ainda não existe e precisa de um tenant para teste.",
        "Enquanto isso, o administrador pode usar o Microsoft Purview (auditoria e DSPM for AI), que guarda prompts e respostas do Microsoft 365 Copilot, fora do PromptShield.",
        "Copilot gratuito do Windows (conta pessoal): sem integração possível com o que existe hoje."]),
    IA(9, "GitHub Copilot CLI (terminal)", AUTO, "github_copilot_cli",
       "Hooks de usuário em ~/.copilot/hooks/promptshield.json. EXPERIMENTAL: só testado com entradas simuladas. O prompt só é monitorado (o Copilot descarta a resposta); ações de ferramenta podem ser negadas.",
       ["O sensor grava só o arquivo ~/.copilot/hooks/promptshield.json (nada mais é alterado).",
        "Abra uma nova sessão do Copilot CLI e mande um prompt sintético.",
        "Não cobre o Copilot dentro do VS Code nem as sugestões em linha."]),
    IA(10, "Claude (web, claude.ai)", EXT, "browser_extension",
       "Extensão do navegador. EXPERIMENTAL: seletores nunca conferidos na página real (A VERIFICAR).", EXT_STEPS),
]
BY_N = {i.n: i for i in CATALOG}
# identificador estável de cada IA (vai para o servidor; o console mostra o nome). Onde a IA gera eventos, é o mesmo valor de `source.app`.
KEY = {1: "chatgpt_web", 2: "copilot_web", 3: "gemini_web", 4: "codex_desktop", 5: "claude_desktop", 6: "claude_code",
       7: "codex_cli", 8: "copilot_desktop", 9: "github_copilot_cli", 10: "claude_web"}
ALL_TOOLS_FROM = {"claude_code", "github_copilot_cli", "browser_extension"}


def render_list() -> str:
    lines = ["Quais IAs você quer monitorar?"]
    for i in CATALOG:
        lines.append(f"  {i.n}) {i.name}   [{TAG[i.state]}]")
    lines.append("Digite os números separados por vírgula (ex.: 1,2,6), ou 'todas'.")
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
    head = f"[{n}] {i.name}: {TAG[i.state].upper()}\n  {i.status}"
    steps = "\n".join(f"  {k}. {s.replace('{COMMAND}', command or '<python> <caminho do sensor.pyz>')}" for k, s in enumerate(i.steps, 1))
    return f"{head}\n{steps}" if steps else head
