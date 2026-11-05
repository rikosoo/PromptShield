"""Relatórios executivo e de conformidade LGPD, em PDF e CSV. Os totais vêm da MESMA função do painel (compute_overview).

Os relatórios são agregados: não trazem texto de prompt nem nomes de pessoas fora do ranking de indicador de risco do
executivo (que carrega o aviso "requer revisão humana"). O modelo de LGPD é um modelo; precisa de revisão jurídica.
"""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime, timedelta, timezone
from typing import Any

from promptshield_detection.taxonomy import load as load_taxonomy
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import pilot as pilot_mod
from app import risk
from app.models import Tenant
from app.routers.analytics import compute_overview

PERSONAL_DATA_CATEGORIES = ("pii", "saude", "financeiro", "rh", "cliente")
KINDS = ("executivo", "lgpd", "piloto")
TITLES = {"executivo": "Relatório executivo de uso de IA", "piloto": "Relatório final do piloto (modo só monitorar)", "lgpd": "Relatório de conformidade LGPD: dados pessoais enviados à IA"}
# fragmento SQL constante (sem entrada do usuário); as categorias entram por parâmetro
PERSONAL_FILTER = ("WHERE e.occurred_at >= :s AND e.occurred_at < :u AND EXISTS (SELECT 1 FROM jsonb_array_elements(a.categories::jsonb) c "
                   "WHERE c->>'id' = ANY(CAST(:cats AS text[])))")
# Metas SUGERIDAS para o piloto (propostas do produto, a combinar com o cliente: não são padrão de mercado nem exigência legal)
PILOT_TARGETS = {"coverage_min": 0.80, "false_positive_max": 0.20, "first_alert_max_hours": 24}
LGPD_NOTE = ("Modelo de relatório. Não constitui parecer jurídico: a base legal, o aviso aos colaboradores e a política de uso "
             "de IA devem ser revisados por um advogado.")


def bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return (datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
            datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1))


def month_range(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return first, nxt - timedelta(days=1)


def _decisions(s: Session, since: datetime, until: datetime) -> dict[str, int]:
    rows = s.execute(text("""SELECT a.decision, count(*) n FROM events e JOIN analyses a ON a.event_pk = e.id
                             WHERE e.occurred_at >= :s AND e.occurred_at < :u GROUP BY 1"""), {"s": since, "u": until})
    return {r.decision: r.n for r in rows}


def _categories(s: Session, since: datetime, until: datetime) -> list[dict]:
    tax = load_taxonomy()
    rows = s.execute(text("""SELECT c->>'id' id, count(*) n FROM events e JOIN analyses a ON a.event_pk = e.id,
                             jsonb_array_elements(a.categories::jsonb) c
                             WHERE e.occurred_at >= :s AND e.occurred_at < :u GROUP BY 1 ORDER BY 2 DESC, 1"""),
                     {"s": since, "u": until})
    return [{"id": r.id, "nome": tax[r.id].nome if r.id in tax else r.id, "events": r.n} for r in rows]


def user_risk(s: Session, start: date, end: date, top: int = 10) -> dict:
    since, until = bounds(start, end)
    rows = s.execute(text("""
        SELECT e.user_id, (array_agg(e.department ORDER BY e.occurred_at DESC))[1] AS department,
               (e.occurred_at AT TIME ZONE 'UTC')::date AS d, count(*) AS events, max(a.risk_score) AS mx,
               count(*) FILTER (WHERE a.risk_score >= :med) AS n_med, count(*) FILTER (WHERE a.risk_score >= :hi) AS n_hi
        FROM events e JOIN analyses a ON a.event_pk = e.id WHERE e.occurred_at >= :s AND e.occurred_at < :u
        GROUP BY e.user_id, 3"""), {"s": since, "u": until, "med": risk.MEDIUM, "hi": risk.HIGH}).all()
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    data = [(r.user_id, r.department, r.d, risk.DayAgg(r.events, r.mx, r.n_med, r.n_hi)) for r in rows]
    return risk.aggregate(days, data, top=top)


def collect(s: Session, tenant: Tenant, kind: str, start: date, end: date) -> dict[str, Any]:
    since, until = bounds(start, end)
    ov = compute_overview(s, since, until)
    base = {"kind": kind, "title": TITLES[kind], "tenant": tenant.name, "demo": tenant.is_demo, "start": start, "end": end,
            "generated_at": datetime.now(timezone.utc), "overview": ov, "decisions": _decisions(s, since, until)}
    if kind == "piloto":
        ps = pilot_mod.summary(s, tenant.id)
        incidents = s.execute(text("""SELECT i.status, count(*) n FROM incidents i JOIN events e ON e.id = i.event_pk
                                      WHERE e.occurred_at >= :s AND e.occurred_at < :u GROUP BY 1"""), {"s": since, "u": until}).all()
        alerts = s.execute(text("SELECT rule, count(*) n FROM alerts WHERE first_seen >= :s AND first_seen < :u GROUP BY 1 ORDER BY 2 DESC, 1"),
                           {"s": since, "u": until}).all()
        base.update(pilot=ps, targets=PILOT_TARGETS, categories=_categories(s, since, until)[:10],
                    incidents=[{"status": x.status, "n": x.n} for x in incidents], alerts=[{"rule": x.rule, "n": x.n} for x in alerts])
    elif kind == "executivo":
        days = (end - start).days + 1
        prev = compute_overview(s, *bounds(start - timedelta(days=days), start - timedelta(days=1)))
        inc = s.execute(text("""SELECT i.severity, i.status, count(*) n FROM incidents i JOIN events e ON e.id = i.event_pk
                                WHERE e.occurred_at >= :s AND e.occurred_at < :u GROUP BY 1, 2"""), {"s": since, "u": until}).all()
        alerts = s.execute(text("SELECT rule, count(*) n FROM alerts WHERE first_seen >= :s AND first_seen < :u GROUP BY 1 ORDER BY 2 DESC, 1"),
                           {"s": since, "u": until}).all()
        r = user_risk(s, start, end)
        base.update(previous=prev["totals"], categories=_categories(s, since, until)[:10],
                    incidents=[{"severity": x.severity, "status": x.status, "n": x.n} for x in inc],
                    alerts=[{"rule": x.rule, "n": x.n} for x in alerts],
                    top_users=[{k: u[k] for k in ("user_id", "department", "score", "events", "high_events")} for u in r["users"]],
                    departments=[{k: d[k] for k in ("department", "score", "users", "users_high", "events")} for d in r["departments"]],
                    score_version=r["score_version"])
    else:
        p = {"s": since, "u": until, "cats": list(PERSONAL_DATA_CATEGORIES)}

        def q(sql: str):
            return s.execute(text(sql.replace("{F}", PERSONAL_FILTER)), p)

        tot = q("""SELECT count(*) events, count(DISTINCT e.user_id) users,
                   count(*) FILTER (WHERE e.personal_account) personal FROM events e JOIN analyses a ON a.event_pk = e.id {F}""").one()
        by_type = q("""SELECT sp->>'type' dtype, count(*) n FROM events e JOIN analyses a ON a.event_pk = e.id,
                       jsonb_array_elements(a.spans::jsonb) sp {F} GROUP BY 1 ORDER BY 2 DESC, 1""").all()
        by_cat = q("""SELECT c->>'id' id, count(DISTINCT e.id) n FROM events e JOIN analyses a ON a.event_pk = e.id,
                      jsonb_array_elements(a.categories::jsonb) c {F} AND c->>'id' = ANY(CAST(:cats AS text[])) GROUP BY 1 ORDER BY 2 DESC, 1""").all()
        by_app = q("SELECT e.app, count(*) n FROM events e JOIN analyses a ON a.event_pk = e.id {F} GROUP BY 1 ORDER BY 2 DESC, 1").all()
        by_dept = q("""SELECT coalesce(e.department,'(sem departamento)') d, count(*) n FROM events e JOIN analyses a ON a.event_pk = e.id {F}
                       GROUP BY 1 ORDER BY 2 DESC, 1""").all()
        dec = q("SELECT a.decision, a.would_decide, count(*) n FROM events e JOIN analyses a ON a.event_pk = e.id {F} GROUP BY 1, 2").all()
        views = s.execute(text("""SELECT count(*) FROM audit_log WHERE action = 'event.original_read' AND at >= :s AND at < :u"""), p).scalar_one()
        tax = load_taxonomy()
        base.update(
            personal={"events": tot.events, "users": tot.users, "personal_account": tot.personal},
            by_type=[{"type": x.dtype, "n": x.n} for x in by_type],
            by_category=[{"id": x.id, "nome": tax[x.id].nome if x.id in tax else x.id, "n": x.n} for x in by_cat],
            by_app=[{"app": x.app, "n": x.n} for x in by_app], by_department=[{"department": x.d, "n": x.n} for x in by_dept],
            personal_decisions=[{"decision": x.decision, "would_decide": x.would_decide, "n": x.n} for x in dec],
            original_views=views, note=LGPD_NOTE)
    return base


# ---------- CSV ----------
def _safe(v: Any) -> str:
    t = "" if v is None else str(v)
    return "'" + t if t[:1] in ("=", "+", "-", "@", "\t", "\r") else t  # evita injeção de fórmula em planilhas


def to_csv(d: dict[str, Any]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["secao", "chave", "valor"])

    def row(sec: str, key: Any, val: Any) -> None:
        w.writerow([sec, _safe(key), _safe(val)])

    row("meta", "relatorio", d["title"])
    row("meta", "tenant", d["tenant"])
    row("meta", "dados_de_exemplo", "sim (sintéticos)" if d["demo"] else "nao")
    row("meta", "periodo_inicio", d["start"].isoformat())
    row("meta", "periodo_fim", d["end"].isoformat())
    for k, v in d["overview"]["totals"].items():
        row("totais", k, v)
    for k, v in sorted(d["decisions"].items()):
        row("decisoes", k, v)
    for x in d["overview"]["daily"]:
        row("alto_risco_por_dia", x["date"], x["high_risk"])
    for x in d["overview"]["by_department"]:
        row("departamentos_eventos", x["department"], x["events"])
        row("departamentos_alto_risco", x["department"], x["high_risk"])
    if d["kind"] == "piloto":
        ps = d["pilot"]
        row("piloto", "inicio", ps["started_at"] or "nao marcado")
        row("piloto", "dia", ps["day"])
        row("cobertura", "usuarios_ativos", ps["coverage"]["active_users"])
        row("cobertura", "usuarios_esperados", ps["coverage"]["expected_users"])
        row("cobertura", "taxa", ps["coverage"]["rate"])
        for x in ps["coverage"]["by_department"]:
            row("cobertura_departamento", x["department"], x["users"])
        fp = ps["false_positive"]
        for k in ("reviewed", "decided", "false_positive", "true_positive", "unsure", "rate", "ci95", "small_sample"):
            row("falso_positivo", k, fp[k])
        row("tempo", "ate_primeiro_alerta_segundos", ps["time_to_first_alert_seconds"])
        row("modo", "somente_monitorar", ps["monitor_only"])
        for k, v in d["targets"].items():
            row("metas_sugeridas (a combinar)", k, v)
        for x in d["categories"]:
            row("categorias", x["id"], x["events"])
        for x in d["incidents"]:
            row("incidentes", x["status"], x["n"])
        for x in d["alerts"]:
            row("alertas", x["rule"], x["n"])
    elif d["kind"] == "executivo":
        for k, v in d["previous"].items():
            row("periodo_anterior", k, v)
        for x in d["categories"]:
            row("categorias", x["id"], x["events"])
        for x in d["incidents"]:
            row("incidentes", f"{x['severity']}/{x['status']}", x["n"])
        for x in d["alerts"]:
            row("alertas", x["rule"], x["n"])
        for x in d["top_users"]:
            row("indicador_risco_usuario (requer revisao humana)", x["user_id"], x["score"])
    else:
        for k, v in d["personal"].items():
            row("dados_pessoais", k, v)
        for x in d["by_type"]:
            row("tipo_de_dado", x["type"], x["n"])
        for x in d["by_category"]:
            row("categoria", x["id"], x["n"])
        for x in d["by_app"]:
            row("ferramenta", x["app"], x["n"])
        for x in d["by_department"]:
            row("departamento", x["department"], x["n"])
        for x in d["personal_decisions"]:
            row("acao_tomada", f"{x['decision']} (politica teria decidido {x['would_decide']})", x["n"])
        row("auditoria", "acessos_ao_texto_original", d["original_views"])
        row("aviso", "modelo", d["note"])
    return ("﻿" + out.getvalue()).encode("utf-8")


# ---------- PDF ----------
def _l1(t: Any) -> str:
    return str(t).encode("latin-1", "replace").decode("latin-1")


def to_pdf(d: dict[str, Any]) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    st = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=st["BodyText"], fontSize=8, leading=10)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                            title=_l1(d["title"]), author="PromptShield")

    def P(t: str, style: str = "BodyText") -> Paragraph:
        return Paragraph(escape(_l1(t)), small if style == "small" else st[style])

    def table(rows: list[list[Any]], widths: list[float] | None = None) -> Table:
        t = Table([[_l1(c) for c in r] for r in rows], colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EDF3")), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]))
        return t

    ov, tot = d["overview"], d["overview"]["totals"]
    story: list[Any] = [P(d["title"], "Title"), P(f"{d['tenant']}  |  período {d['start']:%d/%m/%Y} a {d['end']:%d/%m/%Y}"),
                        P(f"Gerado em {d['generated_at']:%d/%m/%Y %H:%M} UTC. Valores calculados pelas mesmas consultas do painel.", "small")]
    if d["demo"]:
        story.append(P("DADOS DE EXEMPLO: eventos sintéticos, sem relação com pessoas reais.", "Heading3"))
    story += [Spacer(1, 8), P("Resumo", "Heading2"),
              table([["Indicador", "Valor"], ["Eventos", tot["events"]], ["Usuários ativos", tot["users"]],
                     [f"Eventos de alto risco (>= {ov['high_risk_threshold']})", tot["high_risk"]], ["Com código", tot["with_code"]],
                     ["Com dado sensível", tot["with_sensitive"]], ["Ações de agente", tot["agent_actions"]],
                     ["Bloqueados", tot["blocked"]], ["Teriam sido bloqueados (modo monitorar)", tot["would_block"]]], [11 * cm, 4 * cm])]
    if d["kind"] == "piloto":
        ps, fp, cov, tg = d["pilot"], d["pilot"]["false_positive"], d["pilot"]["coverage"], d["targets"]
        pct = lambda v: "sem dados" if v is None else f"{v * 100:.1f}%"  # noqa: E731
        hours = None if ps["time_to_first_alert_seconds"] is None else ps["time_to_first_alert_seconds"] / 3600
        cov_ok = None if cov["rate"] is None else cov["rate"] >= tg["coverage_min"]
        fp_ok = None if fp["rate"] is None or fp["small_sample"] else fp["rate"] <= tg["false_positive_max"]
        ttf_ok = None if hours is None else hours <= tg["first_alert_max_hours"]
        verdict = lambda ok: "sem dados suficientes" if ok is None else ("atingida" if ok else "não atingida")  # noqa: E731
        story += [Spacer(1, 8), P("Metas do piloto (sugeridas, a combinar com o cliente)", "Heading2"),
                  table([["Indicador", "Medido", "Meta sugerida", "Situação"],
                         ["Cobertura de usuários", pct(cov["rate"]), f">= {tg['coverage_min'] * 100:.0f}%", verdict(cov_ok)],
                         ["Taxa de falso positivo (revisada por amostragem)", pct(fp["rate"]), f"<= {tg['false_positive_max'] * 100:.0f}%", verdict(fp_ok)],
                         ["Tempo até o primeiro alerta", "sem alerta" if hours is None else f"{hours:.1f} h", f"<= {tg['first_alert_max_hours']} h", verdict(ttf_ok)]],
                        [6 * cm, 3 * cm, 3.5 * cm, 4 * cm]),
                  Spacer(1, 8), P("Cobertura", "Heading2"),
                  table([["Indicador", "Valor"], ["Usuários ativos no piloto", cov["active_users"]], ["Usuários esperados (informado)", cov["expected_users"] or "não informado"],
                         ["Início do piloto", ps["started_at"] or "não marcado"]], [11 * cm, 4 * cm]),
                  Spacer(1, 4), table([["Departamento", "Usuários"]] + [[x["department"], x["users"]] for x in cov["by_department"]], [11 * cm, 4 * cm]),
                  Spacer(1, 4), table([["Canal", "Ferramenta", "Usuários", "Eventos"]] + [[x["channel"], x["app"], x["users"], x["events"]] for x in cov["by_channel"]],
                                      [4 * cm, 5 * cm, 3 * cm, 3 * cm]),
                  Spacer(1, 8), P("Falsos positivos (revisão humana por amostragem)", "Heading2"),
                  table([["Indicador", "Valor"], ["Itens revisados", fp["reviewed"]], ["Verdadeiros positivos", fp["true_positive"]],
                         ["Falsos positivos", fp["false_positive"]], ["Incertos (fora da taxa)", fp["unsure"]], ["Taxa de falso positivo", pct(fp["rate"])],
                         ["Intervalo de confiança de 95%", "sem dados" if not fp["ci95"] else f"{fp['ci95'][0] * 100:.1f}% a {fp['ci95'][1] * 100:.1f}%"]],
                        [11 * cm, 4 * cm]),
                  P(("ATENÇÃO: amostra pequena (menos de %d itens decididos); a taxa é instável. " % fp["min_reviews"] if fp["small_sample"] else "")
                    + "A taxa vale para os eventos que o produto sinalizou; ela não mede o que passou sem ser sinalizado.", "small"),
                  Spacer(1, 8), P("Modo só monitorar", "Heading2"),
                  P("Nenhuma decisão foi aplicada: " + ("confirmado (todas as políticas em monitorar e zero decisões aplicadas)."
                                                         if ps["monitor_only"] else "ATENÇÃO: há política em modo aplicar ou decisões aplicadas no período."), "BodyText"),
                  Spacer(1, 8), P("Categorias mais frequentes", "Heading2"),
                  table([["Categoria", "Eventos"]] + [[x["nome"], x["events"]] for x in d["categories"]], [11 * cm, 4 * cm]),
                  Spacer(1, 8), P("Incidentes e alertas", "Heading2"),
                  table([["Status do incidente", "Quantidade"]] + [[x["status"], x["n"]] for x in d["incidents"]], [11 * cm, 4 * cm]), Spacer(1, 4),
                  table([["Regra de alerta", "Alertas"]] + [[x["rule"], x["n"]] for x in d["alerts"]], [11 * cm, 4 * cm]),
                  Spacer(1, 8), P("Limites deste relatório", "Heading2"),
                  P("Indicadores de risco pedem revisão humana e não provam má conduta. Os números dependem de os coletores estarem instalados em todos os usuários "
                    "esperados; usuários sem coletor não aparecem. Este relatório não é parecer jurídico.", "small")]
    elif d["kind"] == "executivo":
        pv = d["previous"]
        story += [Spacer(1, 8), P("Comparação com o período anterior de mesma duração", "Heading2"),
                  table([["Indicador", "Atual", "Anterior"], ["Eventos", tot["events"], pv["events"]],
                         ["Alto risco", tot["high_risk"], pv["high_risk"]], ["Com dado sensível", tot["with_sensitive"], pv["with_sensitive"]]],
                        [9 * cm, 3 * cm, 3 * cm]),
                  Spacer(1, 8), P("Departamentos", "Heading2"),
                  table([["Departamento", "Eventos", "Alto risco", "Indicador médio"]] +
                        [[x["department"], x["events"], next((y["high_risk"] for y in ov["by_department"] if y["department"] == x["department"]), 0),
                          x["score"]] for x in d["departments"]], [6 * cm, 3 * cm, 3 * cm, 3 * cm]),
                  Spacer(1, 8), P("Categorias mais frequentes", "Heading2"),
                  table([["Categoria", "Eventos"]] + [[x["nome"], x["events"]] for x in d["categories"]], [11 * cm, 4 * cm]),
                  Spacer(1, 8), P("Incidentes e alertas", "Heading2"),
                  table([["Severidade", "Status", "Incidentes"]] + [[x["severity"], x["status"], x["n"]] for x in d["incidents"]], [5 * cm, 5 * cm, 5 * cm]),
                  Spacer(1, 4), table([["Regra de alerta", "Alertas"]] + [[x["rule"], x["n"]] for x in d["alerts"]], [11 * cm, 4 * cm]),
                  Spacer(1, 8), P("Indicador de risco por usuário (maiores)", "Heading2"),
                  P(risk.DISCLAIMER + f" Versão da fórmula: {d['score_version']}.", "small"),
                  table([["Usuário", "Departamento", "Indicador", "Eventos"]] +
                        [[x["user_id"], x["department"] or "-", x["score"], x["events"]] for x in d["top_users"]], [5 * cm, 5 * cm, 3 * cm, 3 * cm])]
    else:
        pe = d["personal"]
        story += [Spacer(1, 8), P("Dados pessoais enviados a ferramentas de IA", "Heading2"),
                  table([["Indicador", "Valor"], ["Eventos com dado pessoal", pe["events"]], ["Usuários envolvidos", pe["users"]],
                         ["Em conta pessoal (fora do controle corporativo)", pe["personal_account"]],
                         ["Acessos ao texto original (auditados)", d["original_views"]]], [11 * cm, 4 * cm]),
                  Spacer(1, 8), P("Por tipo de dado detectado", "Heading2"),
                  table([["Tipo", "Ocorrências"]] + [[x["type"], x["n"]] for x in d["by_type"]], [11 * cm, 4 * cm]),
                  Spacer(1, 8), P("Por categoria", "Heading2"),
                  table([["Categoria", "Eventos"]] + [[x["nome"], x["n"]] for x in d["by_category"]], [11 * cm, 4 * cm]),
                  Spacer(1, 8), P("Por ferramenta e departamento", "Heading2"),
                  table([["Ferramenta", "Eventos"]] + [[x["app"], x["n"]] for x in d["by_app"]], [11 * cm, 4 * cm]), Spacer(1, 4),
                  table([["Departamento", "Eventos"]] + [[x["department"], x["n"]] for x in d["by_department"]], [11 * cm, 4 * cm]),
                  Spacer(1, 8), P("Ações tomadas", "Heading2"),
                  table([["Decisão", "A política teria decidido", "Eventos"]] +
                        [[x["decision"], x["would_decide"], x["n"]] for x in d["personal_decisions"]], [5 * cm, 6 * cm, 4 * cm]),
                  Spacer(1, 8), P(d["note"], "small")]
    doc.build(story)
    return buf.getvalue()


def render(d: dict[str, Any], fmt: str) -> tuple[bytes, str]:
    data = to_pdf(d) if fmt == "pdf" else to_csv(d)
    return data, hashlib.sha256(data).hexdigest()
