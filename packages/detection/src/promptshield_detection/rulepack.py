"""Pacotes de regras: regras de detecção entregues como DADOS (JSON), não como código.

Por que dados: um pacote de regras NÃO executa código no cliente. Ele só pode (1) procurar padrões no texto (expressão regular restrita ou lista de
termos), (2) apontar para uma categoria que JÁ existe na taxonomia, (3) dizer com que confiança e que texto explica o achado, (4) como mascarar o trecho e
(5) sugerir pesos de risco por categoria. Nada mais: sem rede, sem arquivos, sem chamar funções. Quem decide ativar (e em que modo) é o administrador do cliente.

Formato (JSON; o pacote assinado é entregue pelo fornecedor, ver promptshield_licensing):
    {"v": 1, "typ": "rulepack", "version": "2026.11.1", "min_engine": "2.0", "notes": "...", "weights": {"segredo": 85},
     "rules": [{"id": "tok-interno-x", "category": "segredo", "confidence": 0.9, "rule": "Token interno do sistema X",
                "kind": "regex", "pattern": "\\bXTK-[A-Z0-9]{16}\\b", "fold": false, "span_type": "xtk", "masked": "XTK-****"},
               {"id": "projeto-fenix", "category": "estrategia_ma", "confidence": 0.8, "rule": "Menção ao projeto Fênix",
                "kind": "terms", "terms": ["projeto fenix", "projeto fênix"], "whole_word": true}]}

Segurança das expressões regulares (limite honesto): Python não tem tempo limite para `re`. Por isso a validação RECUSA os padrões que costumam explodir
(repetição dentro de repetição, retrovisor, repetição acima de 200) e há um teste de orçamento de tempo em processo separado antes de aceitar o pacote.
O pacote só chega ao cliente assinado pelo fornecedor, então isto protege contra erro de quem escreve a regra, não contra um fornecedor malicioso."""
from __future__ import annotations

import json
import re
import subprocess  # noqa: S404 - usado só para rodar o teste de orçamento de tempo em processo separado, com o próprio Python
import sys
from dataclasses import dataclass
from typing import Any

from .models import Finding
from .textnorm import fold

try:                                                   # Python 3.11+
    import re._parser as _sre
    from re._constants import MAXREPEAT
except ImportError:                                    # pragma: no cover
    _sre = None
    MAXREPEAT = 0

PACK_TYPE = "rulepack"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,60}$")
PACK_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[.-][A-Za-z][0-9A-Za-z]*)?$")
MAX_RULES, MAX_PATTERN, MAX_TERMS, MAX_TERM_LEN, MAX_RULE_TEXT, MAX_NOTES = 500, 300, 2000, 100, 200, 1000
MAX_REPEAT_BOUND = 200
MAX_MATCHES_PER_RULE, MAX_MATCHES_TOTAL = 20, 200
SLOW_SECONDS = 0.5
ENGINE_MIN_DEFAULT = "2.0"


class PackError(Exception):
    """Pacote inválido. `errors` lista TUDO o que está errado (para o fornecedor corrigir de uma vez)."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors[:5]) + (f" (+{len(errors) - 5})" if len(errors) > 5 else ""))
        self.errors = errors


# ---------------------------------------------------------------- expressões regulares: o que NÃO se aceita
def _children(op, av):
    from re._constants import ASSERT, ASSERT_NOT, BRANCH, GROUPREF_EXISTS, MAX_REPEAT, MIN_REPEAT, SUBPATTERN
    if op == SUBPATTERN:
        return [av[3]]
    if op == BRANCH:
        return list(av[1])
    if op in (MAX_REPEAT, MIN_REPEAT) or getattr(op, "name", "") == "POSSESSIVE_REPEAT":
        return [av[2]]
    if op in (ASSERT, ASSERT_NOT):
        return [av[1]]
    if op == GROUPREF_EXISTS:
        return [x for x in (av[1], av[2]) if x]
    return []


def _walk(parsed):
    for op, av in parsed:
        yield op, av
        for sub in _children(op, av):
            yield from _walk(sub)


def regex_problems(pattern: str) -> list[str]:
    """Motivos para recusar uma expressão regular (lista vazia = aceita). Conservador de propósito."""
    if not isinstance(pattern, str) or not pattern:
        return ["padrão vazio"]
    if len(pattern) > MAX_PATTERN:
        return [f"padrão com mais de {MAX_PATTERN} caracteres"]
    if _sre is None:                                   # pragma: no cover
        return ["este Python não permite analisar a expressão regular"]
    try:
        parsed = _sre.parse(pattern)
    except (re.error, RecursionError, OverflowError) as exc:
        return [f"padrão inválido: {exc}"]
    from re._constants import GROUPREF, GROUPREF_EXISTS, MAX_REPEAT, MIN_REPEAT
    problems: list[str] = []
    for op, av in _walk(parsed):
        name = getattr(op, "name", str(op))
        if op in (GROUPREF, GROUPREF_EXISTS):
            problems.append("retrovisor (\\1, (?(1)...)) não é aceito")
        elif op in (MAX_REPEAT, MIN_REPEAT) or name == "POSSESSIVE_REPEAT":
            lo, hi, sub = av
            if hi != MAXREPEAT and hi > MAX_REPEAT_BOUND:
                problems.append(f"repetição acima de {MAX_REPEAT_BOUND} ({{{lo},{hi}}})")
            inner = [a[1] for o, a in _walk(sub) if o in (MAX_REPEAT, MIN_REPEAT) or getattr(o, "name", "") == "POSSESSIVE_REPEAT"]
            multi, unbounded = any(h == MAXREPEAT or h > 1 for h in inner), any(h == MAXREPEAT for h in inner)
            if (hi == MAXREPEAT and multi) or (hi > 1 and unbounded):                  # (a+)+, (a{1,2})+ e (.*a){20}: tempo explosivo; (\d{1,3}\.){3} e (\d+)? passam
                problems.append("repetição dentro de repetição, como (a+)+ ou (.*a){20}, pode travar o servidor")
    return sorted(set(problems))


ADVERSARIAL = ("a" * 4000, "a" * 3999 + "!", "ab" * 2000, "0123456789" * 400, " " * 4000, "A1-" * 1300, "x@" + "a." * 1900, "-" * 4000, "\n".join(["ab12"] * 900), "é" * 4000)
_BUDGET_CODE = r"""
import json, re, sys, time
items = json.load(sys.stdin)
texts = items["texts"]
for it in items["rules"]:
    rx = re.compile(it["pattern"], re.IGNORECASE if it["ci"] else 0)
    t0 = time.perf_counter()
    for t in texts:
        rx.search(t)
    print(json.dumps({"id": it["id"], "s": round(time.perf_counter() - t0, 3)}), flush=True)
"""
STEP_TIMEOUT = 4.0
MAX_CULPRITS = 10


def budget_problems(payload: dict[str, Any], timeout: float = STEP_TIMEOUT) -> list[str]:
    """Roda cada expressão regular contra textos adversariais, em PROCESSO SEPARADO com tempo limite, e devolve as que passaram de `SLOW_SECONDS`.
    Se uma regra trava, ela é isolada (o processo é encerrado) e as demais seguem: a validação nunca fica presa por causa de uma regra ruim."""
    rules = [{"id": r["id"], "pattern": _folded_pattern(r), "ci": "i" in str(r.get("flags", ""))} for r in payload.get("rules", []) if isinstance(r, dict) and r.get("kind") == "regex"]
    problems: list[str] = []
    for _ in range(MAX_CULPRITS + 1):
        if not rules:
            break
        stdout, hung = "", False
        try:
            proc = subprocess.run([sys.executable, "-I", "-c", _BUDGET_CODE], input=json.dumps({"rules": rules, "texts": list(ADVERSARIAL)}),  # noqa: S603
                                  capture_output=True, text=True, timeout=timeout, check=True)
            stdout = proc.stdout
        except subprocess.TimeoutExpired as exc:
            hung = True
            out = exc.stdout or ""
            stdout = out.decode("utf-8", "ignore") if isinstance(out, bytes) else out
        except (subprocess.CalledProcessError, OSError) as exc:
            return problems + [f"o teste de tempo das expressões regulares falhou: {type(exc).__name__}"]
        done: dict[str, float] = {}
        for line in stdout.splitlines():
            try:
                row = json.loads(line)
                done[row["id"]] = float(row["s"])
            except (ValueError, KeyError, TypeError):
                continue
        problems += [f"regra {rid}: padrão lento ({sec} s nos textos de teste)" for rid, sec in done.items() if sec > SLOW_SECONDS]
        if not hung:
            break
        pending = [r for r in rules if r["id"] not in done]
        if not pending:
            break
        problems.append(f"regra {pending[0]['id']}: padrão trava o servidor (não terminou em {timeout:.0f} s nos textos de teste)")
        rules = pending[1:]                                  # isola a culpada e testa o resto
    else:
        problems.append("muitas regras lentas: corrija o pacote")
    return problems


def _folded_pattern(rule: dict[str, Any]) -> str:
    return str(rule.get("pattern", ""))


# ---------------------------------------------------------------- validação e leitura
@dataclass(frozen=True)
class PackRule:
    id: str
    category: str
    confidence: float
    rule: str
    kind: str                     # regex | terms
    rx: re.Pattern[str]
    fold: bool                    # procurar no texto SEM acento e em minúsculas (termos sempre)
    span_type: str | None
    masked: str | None


@dataclass(frozen=True)
class Match:
    rule: PackRule
    start: int
    end: int


@dataclass(frozen=True)
class RulePack:
    version: str
    notes: str
    min_engine: str
    weights: dict[str, int]
    rules: tuple[PackRule, ...]

    def scan(self, text: str) -> list[Match]:
        """Todas as ocorrências (limitadas por regra e no total). O texto procurado nunca é alterado nem guardado aqui."""
        if not text or not self.rules:
            return []
        low = None
        out: list[Match] = []
        for r in self.rules:
            hay = text
            if r.fold:
                low = low if low is not None else fold(text)
                hay = low
            n = 0
            for m in r.rx.finditer(hay):
                if m.end() == m.start():
                    continue
                out.append(Match(r, m.start(), m.end()))
                n += 1
                if n >= MAX_MATCHES_PER_RULE or len(out) >= MAX_MATCHES_TOTAL:
                    break
            if len(out) >= MAX_MATCHES_TOTAL:
                break
        return out

    def findings(self, matches: list[Match]) -> list[Finding]:
        """Achados do motor. Regra sem `masked` vira achado de categoria (sem posição, nada é mascarado)."""
        out: list[Finding] = []
        seen_plain: set[str] = set()
        for m in matches:
            r = m.rule
            text = f"Regra do pacote {self.version}: {r.rule}"
            if r.masked:
                out.append(Finding(r.category, r.confidence, text, r.span_type or f"pack_{r.id}", m.start, m.end, r.masked))
            elif r.id not in seen_plain:
                seen_plain.add(r.id)
                out.append(Finding(r.category, r.confidence, text))
        return out

    def summary(self) -> dict[str, Any]:
        return {"version": self.version, "rules": len(self.rules), "weights": dict(self.weights),
                "by_category": {c: sum(1 for r in self.rules if r.category == c) for c in sorted({r.category for r in self.rules})}}


def _engine_ok(min_engine: str) -> bool:
    from .scoring import ENGINE_VERSION

    def nums(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in re.findall(r"\d+", v)[:3])

    return nums(min_engine) <= nums(ENGINE_VERSION)


def validate(payload: Any, categories: set[str] | None = None) -> list[str]:
    """Erros do pacote (lista vazia = válido). Não compila nada além do necessário para validar."""
    if categories is None:
        from .taxonomy import load
        categories = set(load())
    errs: list[str] = []
    if not isinstance(payload, dict):
        return ["o pacote precisa ser um objeto JSON"]
    if payload.get("typ") != PACK_TYPE or payload.get("v") != 1:
        errs.append("não é um pacote de regras (typ/v)")
    v = payload.get("version")
    if not isinstance(v, str) or not PACK_VERSION_RE.match(v):
        errs.append(f"versão inválida: {v!r}")
    if not isinstance(payload.get("notes", ""), str) or len(payload.get("notes", "")) > MAX_NOTES:
        errs.append(f"notas: texto de até {MAX_NOTES} caracteres")
    me = payload.get("min_engine", ENGINE_MIN_DEFAULT)
    if not isinstance(me, str) or not re.fullmatch(r"\d+(?:\.\d+){0,2}", me):
        errs.append("min_engine inválido")
    elif not _engine_ok(me):
        errs.append(f"este pacote exige o motor {me} ou mais novo")
    w = payload.get("weights", {})
    if not isinstance(w, dict):
        errs.append("weights precisa ser um objeto")
    else:
        for c, val in w.items():
            if c not in categories:
                errs.append(f"weights: categoria desconhecida {c!r}")
            if not isinstance(val, int) or isinstance(val, bool) or not 0 <= val <= 100:
                errs.append(f"weights[{c}]: número inteiro de 0 a 100")
    rules = payload.get("rules")
    if not isinstance(rules, list) or not rules:
        errs.append("o pacote precisa ter pelo menos uma regra")
        return errs
    if len(rules) > MAX_RULES:
        errs.append(f"no máximo {MAX_RULES} regras")
    seen: set[str] = set()
    for i, r in enumerate(rules[:MAX_RULES]):
        tag = f"regra {i + 1}"
        if not isinstance(r, dict):
            errs.append(f"{tag}: precisa ser um objeto")
            continue
        rid = r.get("id")
        tag = f"regra {rid!r}" if isinstance(rid, str) else tag
        if not isinstance(rid, str) or not ID_RE.match(rid):
            errs.append(f"{tag}: id precisa ser minúsculo, de 3 a 61 caracteres (letras, números, - e _)")
        elif rid in seen:
            errs.append(f"{tag}: id repetido")
        else:
            seen.add(rid)
        if r.get("category") not in categories:
            errs.append(f"{tag}: categoria {r.get('category')!r} não existe na taxonomia")
        c = r.get("confidence")
        if not isinstance(c, (int, float)) or isinstance(c, bool) or not 0.05 <= c <= 0.99:
            errs.append(f"{tag}: confiança entre 0,05 e 0,99")
        txt = r.get("rule")
        if not isinstance(txt, str) or not 3 <= len(txt) <= MAX_RULE_TEXT:
            errs.append(f"{tag}: texto da regra de 3 a {MAX_RULE_TEXT} caracteres (aparece para o analista)")
        for k in ("span_type", "masked"):
            if r.get(k) is not None and (not isinstance(r[k], str) or not 1 <= len(r[k]) <= 60 or "\n" in r[k]):
                errs.append(f"{tag}: {k} é um texto curto de uma linha")
        extra = set(r) - {"id", "category", "confidence", "rule", "kind", "pattern", "terms", "fold", "flags", "whole_word", "span_type", "masked"}
        if extra:
            errs.append(f"{tag}: campos desconhecidos {sorted(extra)}")
        kind = r.get("kind")
        if kind == "regex":
            for p in regex_problems(r.get("pattern", "")):
                errs.append(f"{tag}: {p}")
            if r.get("flags", "") not in ("", "i"):
                errs.append(f"{tag}: flags aceitas: vazio ou 'i'")
        elif kind == "terms":
            t = r.get("terms")
            if not isinstance(t, list) or not t or len(t) > MAX_TERMS or not all(isinstance(x, str) and 2 <= len(x.strip()) <= MAX_TERM_LEN for x in t):
                errs.append(f"{tag}: terms: lista de 1 a {MAX_TERMS} textos de 2 a {MAX_TERM_LEN} caracteres")
        else:
            errs.append(f"{tag}: kind precisa ser 'regex' ou 'terms'")
    return errs


def compile_rule(r: dict[str, Any]) -> PackRule:
    if r["kind"] == "terms":
        terms = sorted({fold(t.strip()) for t in r["terms"] if t.strip()}, key=lambda x: (-len(x), x))
        body = "|".join(re.escape(t) for t in terms)
        pat = rf"(?<!\w)(?:{body})(?!\w)" if r.get("whole_word") else body
        rx, fold_it = re.compile(pat), True
    else:
        rx, fold_it = re.compile(r["pattern"], re.IGNORECASE if r.get("flags") == "i" else 0), bool(r.get("fold"))
    return PackRule(r["id"], r["category"], float(r["confidence"]), r["rule"], r["kind"], rx, fold_it, r.get("span_type"), r.get("masked"))


def load(payload: Any, categories: set[str] | None = None, *, check_budget: bool = False) -> RulePack:
    """Valida e compila. `check_budget=True` roda também o teste de tempo (processo separado): use ao ACEITAR um pacote, não a cada leitura."""
    errs = validate(payload, categories)
    if not errs and check_budget:
        errs = budget_problems(payload)
    if errs:
        raise PackError(errs)
    return RulePack(payload["version"], str(payload.get("notes", "")), str(payload.get("min_engine", ENGINE_MIN_DEFAULT)),
                    {k: int(v) for k, v in payload.get("weights", {}).items()}, tuple(compile_rule(r) for r in payload["rules"]))
