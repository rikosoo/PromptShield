"""Os testes antigos exercitam a aplicação LEGADA de decisões (bloquear/pedir confirmação); o padrão real do sensor é PASSIVO.
Por isso ligam PROMPTSHIELD_ENFORCEMENT=1; os testes marcados @pytest.mark.passive rodam com o padrão real."""
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "passive: roda com o padrão real do sensor (passivo, sem PROMPTSHIELD_ENFORCEMENT)")


@pytest.fixture(autouse=True)
def _legacy_enforcement(request, monkeypatch):
    if "passive" in request.keywords:
        monkeypatch.delenv("PROMPTSHIELD_ENFORCEMENT", raising=False)
    else:
        monkeypatch.setenv("PROMPTSHIELD_ENFORCEMENT", "1")
