"""Estados da licença na instalação do cliente. Função pura: dado o que está guardado e o relógio, devolve o estado e o que ele permite.

Precedência: nao_ativado, encerrado, expirado, em_tolerancia, sem_contato, ativo.

O que cada estado permite (nada apaga dados e nenhum interrompe as ferramentas dos funcionários; os sensores seguem em falha aberta):
  nao_ativado   sem inspeção, sem matrícula (falta o código de ativação)
  ativo         tudo
  sem_contato   tudo; avisa o administrador (a autorização local ainda vale)
  em_tolerancia tudo; mostra o prazo para regularizar
  expirado      sem NOVAS matrículas; a inspeção continua; consulta e exportação continuam
  encerrado     sem novas matrículas; a inspeção segue a política do contrato (`on_end`); consulta e exportação continuam
  suspenso      faltou a validação com o fornecedor por mais de `suspend_after_days`: a inspeção PARA e alterações ficam bloqueadas; consulta e
                exportação continuam; volta sozinho na próxima validação bem-sucedida (a autorização nova zera a contagem)

Falta de validação (autorizações com `warn_after_days`/`suspend_after_days`): a contagem parte de `issued_at` + `renew_after_hours`, ou seja, do
instante em que a validação seguinte deveria ter ocorrido. Só depois de `warn_after_days` o CLIENTE vê o aviso (antes disso quem acompanha é o
fornecedor, no painel dele); depois de `suspend_after_days` a inspeção para. Tudo vem da autorização ASSINADA, nada do relógio de quem a recebeu.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .authorization import Authorization


class State(StrEnum):
    NAO_ATIVADO = "nao_ativado"
    ATIVO = "ativo"
    SEM_CONTATO = "sem_contato"
    EM_TOLERANCIA = "em_tolerancia"
    EXPIRADO = "expirado"
    ENCERRADO = "encerrado"
    SUSPENSO = "suspenso"


@dataclass(frozen=True)
class LicenseState:
    state: State
    can_enroll: bool
    inspecting: bool
    message: str
    deadline: datetime | None = None      # o prazo que importa neste estado (fim da autorização, da tolerância...)
    days_left: int | None = None
    max_devices: int | None = None


def _days(delta: timedelta) -> int:
    return max(0, delta.days)


def evaluate(auth: Authorization | None, now: datetime, *, last_success: datetime | None = None, last_attempt_failed: bool = False) -> LicenseState:
    if auth is None:
        return LicenseState(State.NAO_ATIVADO, False, False, "Instalação sem ativação. Informe o código de ativação recebido do fornecedor.")
    mx = auth.max_devices
    if auth.status == "closed":
        stop = auth.on_end == "stop_inspection"
        msg = ("Contrato encerrado: a inspeção está PARADA conforme o contrato. Consulta e exportação continuam. Fale com o fornecedor."
               if stop else "Contrato encerrado: a inspeção continua conforme o contrato; novas máquinas não podem ser matriculadas.")
        return LicenseState(State.ENCERRADO, False, not stop, msg, max_devices=mx)
    overdue = now - (auth.issued_at + timedelta(hours=auth.renew_after_hours))      # quanto passou do momento em que a próxima validação era esperada
    if auth.suspend_after_days is not None and overdue >= timedelta(days=auth.suspend_after_days):
        return LicenseState(State.SUSPENSO, False, False,
                            f"Licença SUSPENSA: faltou a validação com o fornecedor por mais de {auth.suspend_after_days} dias. A inspeção está PARADA e "
                            "alterações estão bloqueadas; consulta e exportação continuam. Volta sozinha na próxima validação bem-sucedida: confira se este "
                            "servidor alcança o serviço de licenças (HTTPS) e fale com o fornecedor.", days_left=0, max_devices=mx)
    if now > auth.tolerance_end or now > auth.auth_expires:
        why = ("o contrato e a tolerância terminaram" if now > auth.tolerance_end
               else "a autorização local venceu sem renovação (sem contato com o serviço de licenças)")
        return LicenseState(State.EXPIRADO, False, True,
                            f"Licença expirada: {why}. Novas máquinas não podem ser matriculadas; a inspeção, a consulta e a exportação continuam.",
                            deadline=min(auth.tolerance_end, auth.auth_expires), days_left=0, max_devices=mx)
    if now > auth.contract_end:
        left = auth.tolerance_end - now
        return LicenseState(State.EM_TOLERANCIA, True, True,
                            f"Contrato vencido em {auth.contract_end:%d/%m/%Y}. Em tolerância por mais {_days(left)} dia(s); regularize com o fornecedor.",
                            deadline=auth.tolerance_end, days_left=_days(left), max_devices=mx)
    if auth.warn_after_days is not None:       # regra nova: o cliente só é avisado depois de `warn_after_days` sem validar
        if overdue >= timedelta(days=auth.warn_after_days):
            suspend_at = auth.issued_at + timedelta(hours=auth.renew_after_hours) + timedelta(days=auth.suspend_after_days) if auth.suspend_after_days is not None else None
            tail = (f" Se continuar assim, a inspeção será suspensa em {_days(suspend_at - now)} dia(s)." if suspend_at is not None else "")
            return LicenseState(State.SEM_CONTATO, True, True,
                                f"Sem validação com o fornecedor há {_days(overdue)} dia(s).{tail} Confira se este servidor alcança o serviço de licenças "
                                "(HTTPS, saída para a internet) e fale com o fornecedor.",
                                deadline=suspend_at, days_left=_days(suspend_at - now) if suspend_at is not None else None, max_devices=mx)
        return LicenseState(State.ATIVO, True, True, "Licença ativa.", deadline=auth.auth_expires, days_left=_days(auth.auth_expires - now), max_devices=mx)
    missed = last_attempt_failed and (last_success is None or now - last_success > timedelta(hours=auth.renew_after_hours) * 1.5)
    if missed:
        left = auth.auth_expires - now
        return LicenseState(State.SEM_CONTATO, True, True,
                            f"Sem contato com o serviço de licenças. A autorização local vale por mais {_days(left)} dia(s) e tudo segue funcionando.",
                            deadline=auth.auth_expires, days_left=_days(left), max_devices=mx)
    return LicenseState(State.ATIVO, True, True, "Licença ativa.", deadline=auth.auth_expires, days_left=_days(auth.auth_expires - now), max_devices=mx)
