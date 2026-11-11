# PromptShield {{VERSION}}: guia de instalação

O PromptShield observa o uso de ferramentas de IA na sua empresa (o que é enviado, o que é detectado e o risco de cada envio) e **alerta**. Ele é
**passivo**: nunca bloqueia nem altera o que as pessoas fazem. Este pacote instala tudo **no seu próprio servidor**: os dados ficam com você.

Tempo estimado: 20 a 40 minutos (a maior parte é carregar as imagens).

---

## 1. O que você precisa antes de começar

| Item | Detalhe |
|---|---|
| Servidor | Linux (Ubuntu 22.04 ou mais novo, Debian, RHEL), ou Windows/macOS com Docker Desktop |
| Memória e disco | 4 GB de memória (mínimo) e 20 GB livres |
| Docker | Docker Engine 24 ou mais novo e Docker Compose v2 (`docker compose version` precisa funcionar) |
| Rede | **Saída HTTPS (porta 443) para `{{LICENSE_HOST}}`**: é por onde o servidor valida a licença (seção 6) |
| Relógio | Hora correta (use NTP): licença e certificados dependem dela |
| Do fornecedor | Este pacote (.zip), o **SHA-256** do arquivo e o **código de ativação** (enviado por outro canal) |

## 2. Confira o arquivo recebido

Compare o SHA-256 do `.zip` com o que o fornecedor informou. Se for diferente, **não instale**: baixe de novo.

- Linux: `sha256sum promptshield-onprem-{{VERSION}}.zip`
- macOS: `shasum -a 256 promptshield-onprem-{{VERSION}}.zip`
- Windows (PowerShell): `Get-FileHash promptshield-onprem-{{VERSION}}.zip -Algorithm SHA256`

## 3. Instale

1. Descompacte o `.zip` numa pasta do servidor (por exemplo `/opt/promptshield`). Entre na pasta.
2. Rode o instalador:
   - **Linux ou macOS:** `bash instalar.sh`
   - **Windows:** abra o PowerShell na pasta e rode `.\instalar.ps1` (se o Windows bloquear scripts: `powershell -ExecutionPolicy Bypass -File .\instalar.ps1`)
3. Ele pergunta o **nome da empresa** e o **e-mail do administrador** (será o seu login).
4. No final ele mostra o endereço do console e uma **senha temporária**. Anote: ela aparece só uma vez.

O instalador: confere os arquivos, cria o `.env` com senhas aleatórias, carrega as imagens, sobe os serviços e cria o administrador. Pode ser rodado de novo sem perder nada.

## 4. Primeiro acesso

1. Abra o endereço mostrado (por padrão `http://localhost:3000`, no próprio servidor) e entre com o e-mail e a senha temporária. O sistema pede para você **definir a sua senha**: mínimo de 8 caracteres, com letra minúscula, maiúscula, número e caractere especial.
2. Aparece uma faixa vermelha "Instalação sem ativação". Vá em **Licença** e informe o **código de ativação** do fornecedor (vale uma vez e por poucos dias). A faixa some quando a licença fica **Ativa**.
3. Em **Administração → Colaboradores** cadastre as outras pessoas que usarão o console, cada uma com a sua função (Administrador, Analista, Auditor ou Leitura). O sistema gera uma senha temporária para cada uma.
4. Em **Dispositivos**, conecte as máquinas dos funcionários seguindo as instruções da própria tela. Avise os funcionários: o monitoramento deve ser transparente, e o aviso é obrigação da sua empresa.

## 5. Deixar a equipe acessar (HTTPS)

Por padrão o console só abre **no próprio servidor** (`127.0.0.1`). Para a equipe e as máquinas monitoradas acessarem, ponha na frente um proxy reverso **com HTTPS** (nunca exponha em HTTP). Exemplo com Caddy (cuida do certificado sozinho):

```
console.suaempresa.com.br {
    reverse_proxy localhost:3000
}
api.suaempresa.com.br {
    reverse_proxy localhost:8000
}
```

Depois, no arquivo `.env`, ajuste `PUBLIC_BASE_URL=https://console.suaempresa.com.br` e rode `docker compose up -d`. Use o endereço HTTPS da API (`https://api.suaempresa.com.br`) ao instalar os sensores nas máquinas.

## 6. A validação da licença com o fornecedor

**O que é enviado:** o identificador desta instalação, o nome do servidor, a versão do PromptShield e a **quantidade** de máquinas ativas, assinados e por HTTPS. **Nunca** são enviados prompts, textos, arquivos, nomes de usuários ou qualquer dado dos seus funcionários.

**Quando:** toda semana, automaticamente. Se uma tentativa falhar, o servidor tenta de novo a cada 15 minutos.

**Se a validação deixar de funcionar** (internet bloqueada, `{{LICENSE_HOST}}` fora do ar, relógio errado), os prazos contam a partir do momento em que a validação era esperada:

| Quando | O que acontece |
|---|---|
| Logo na primeira falha | O fornecedor é avisado. Para você, nada muda |
| Depois de **10 dias** | O console mostra um aviso em todas as telas |
| Depois de **21 dias** | A **inspeção de novos prompts é suspensa** e alterações ficam bloqueadas. Consulta e exportação dos dados continuam, e **as ferramentas dos funcionários seguem funcionando** (nada é bloqueado para eles) |

A suspensão **se desfaz sozinha** na primeira validação bem-sucedida. Nada é apagado em nenhum momento.

**Para resolver:** libere a saída HTTPS (443) deste servidor para `{{LICENSE_HOST}}`, confira o relógio (NTP) e, na tela **Licença**, use **Renovar agora**. Se a sua empresa usa proxy para a saída de internet, avise o fornecedor.

## 7. Backup (faça desde o primeiro dia)

Rode `bash backup.sh` (Linux/macOS). Ele grava na pasta `backups/`: o **banco**, o **`.env`** e a **identidade da licença**. Copie essa pasta para **fora do servidor**.

- Sem a **identidade da licença**, a instalação volta a "não ativada" e é preciso pedir um código novo ao fornecedor.
- A **chave dos textos originais** fica no `.env`: guarde-a **separada** do backup do banco. Sem ela, textos originais cifrados não podem ser lidos.
- Para **restaurar** um backup, fale com o fornecedor (o procedimento exige conferência para não sobrescrever dados).

## 8. Atualizar para uma versão nova

**Nada é instalado sozinho.** A cada validação semanal da licença o fornecedor pode avisar que há versão nova. O caminho é este:

1. No console, em **Administração > Atualizações** (só o administrador), aparece a versão, as notas e se é correção de segurança. Clique em **Aprovar o download**. O servidor baixa o arquivo do fornecedor e confere a assinatura e o SHA-256; ele **não instala nada**.
2. Quando o status ficar **Pronta para instalar**, entre no servidor, na pasta do PromptShield, e rode:

```bash
bash atualizar.sh
```

O script confere de novo o arquivo e o conteúdo, **faz o backup antes**, guarda os arquivos atuais em `anterior/<versão>/`, troca os arquivos do pacote (o `.env`, os dados e a licença **não** são tocados), sobe a versão nova (o banco é atualizado sozinho na partida) e confere que a API informa a versão nova. Ele recusa voltar para uma versão menor.

**Se algo der errado:** o script para e diz onde. Os arquivos antigos estão em `anterior/<versão>/` e o backup em `backups/`. Não apague nada e fale com o fornecedor: voltar atrás depois que o banco foi atualizado exige restaurar o backup, e isso deve ser feito com acompanhamento.

**Pacotes de regras** (novas detecções) são outra coisa: não exigem reinstalar nada. Eles chegam do mesmo jeito, ficam **guardados sem efeito**, e você os põe em **sombra** (só registra o que casaria, sem mudar nenhum resultado), olha os números e então **promove a ativo**. Dá para desativar a qualquer momento: volta ao padrão de fábrica na hora.

*(Estes procedimentos foram provados com um Docker simulado nos testes e ainda não foram validados em campo, nem no Windows: por isso o backup antes e o acompanhamento do fornecedor na primeira atualização.)*

## 9. Problemas comuns

| Sintoma | O que fazer |
|---|---|
| "Docker não encontrado" ou "sem permissão" | Instale o Docker; no Linux, use um usuário do grupo `docker` ou `sudo` |
| "A API não respondeu em 5 minutos" | `docker compose logs --tail 50 api`. Falta de memória é a causa mais comum |
| Console abre, mas a licença mostra "Sem contato" | Libere a saída HTTPS para `{{LICENSE_HOST}}` e confira o relógio (seção 6) |
| "Código de ativação inválido, usado ou expirado" | Peça um código novo ao fornecedor (cada um vale uma vez) |
| Esqueci a senha | Outro administrador gera uma senha temporária em **Colaboradores → Nova senha** |
| Esqueci a senha do **único** administrador | `docker compose exec api python -m app.cli set-password --email SEU_EMAIL --generate` |

## 10. Parar, reiniciar e desinstalar

- Parar sem perder nada: `docker compose stop`. Reiniciar: `docker compose up -d`.
- Remover os serviços **mantendo** os dados: `docker compose down`.
- **Nunca** use `docker compose down -v` se quiser manter os dados: ele **apaga o banco e a identidade da licença** de forma definitiva.

## 11. Privacidade em poucas linhas

- Por padrão o PromptShield guarda o texto **já mascarado** (CPF, chaves, senhas etc. aparecem parcialmente ocultos). O texto original só é guardado se um administrador ligar essa opção em **Privacidade e segurança**; fica cifrado e ler exige justificativa e fica em auditoria.
- Nenhum conteúdo dos seus funcionários vai para serviços externos de IA.
- Os dados ficam neste servidor, sob o seu controle.

Dúvidas: fale com o fornecedor que lhe enviou este pacote.
