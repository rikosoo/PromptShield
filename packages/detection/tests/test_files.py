"""Nome de arquivo anexado: sinal de risco só pelo nome; o nome é mascarado e a pasta some."""
from promptshield_detection.engine import analyze


def run(*names):
    return analyze({"kind": "file_upload", "content": {"text": "", "attachments": [{"name": n} for n in names]}})


def test_sensitive_names_become_categories():
    ids = lambda *n: {c["id"] for c in run(*n).categories}   # noqa: E731
    assert "segredo" in ids(".env.production") and "segredo" in ids("id_rsa") and "segredo" in ids("cert.pfx")
    assert "rh" in ids("Folha de Pagamento 2026.xlsx") and "sql" in ids("clientes_backup.sql")
    assert "juridico" in ids("contrato-fornecedor.pdf") and "logs" in ids("app.log")


def test_harmless_names_stay_clean_and_flag_is_set():
    a = run("foto-ferias.png", "relatorio.pdf")
    assert a.categories == [] and a.flags["has_attachments"] is True and a.risk["score"] == 0


def test_name_is_masked_and_folder_dropped():
    a = run("C:\\Users\\maria\\Desktop\\cpf_529.982.247-25.pdf", "/home/joao/ana@empresa.com.br-notas.txt")
    assert [x["name"] for x in a.attachments] == ["cpf_***.***.***-25.pdf", "***@empresa.com.br-notas.txt"] or "529.982" not in str(a.attachments)
    assert "maria" not in str(a.attachments) and "529.982.247" not in str(a.attachments) and "ana@" not in str(a.attachments)


def test_limits_and_garbage():
    a = run(*[f"f{i}.txt" for i in range(40)])
    assert len(a.attachments) == 20
    assert analyze({"kind": "file_upload", "content": {"attachments": ["x", None, {"name": ""}]}}).attachments == []
