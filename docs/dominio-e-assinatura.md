# Domínio, subdomínios por cliente e executável assinado

Nada aqui foi contratado nem executado. Preços e prazos são ordens de grandeza de memória, **A VERIFICAR** nos sites dos fornecedores antes de decidir.

## Domínio e subdomínio por cliente

Sim, dá para dar um subdomínio a cada cliente: `acme.seudominio.com.br`, `beta.seudominio.com.br`.

1. **Registrar o domínio.** `.com.br` é no Registro.br (exige CPF ou CNPJ). Antes de investir na marca, pesquise "PromptShield" no INPI e na internet: o nome pode já estar em uso.
2. **DNS.** Um registro curinga `*.seudominio.com.br` apontando para o servidor. Cada cliente novo não exige mexer no DNS.
3. **HTTPS.** Um certificado curinga (`*.seudominio.com.br`) gratuito pelo Let's Encrypt, validado por DNS. O proxy reverso (Caddy ou Traefik, por exemplo) renova sozinho.
4. **Console e login.** Hoje o cliente é identificado pelo login e pela chave, não pelo endereço. O subdomínio seria só a "cara" da empresa (e o lugar do `redirect_uri` do login). Dá para fazer o console recusar usuário de outra empresa no subdomínio errado; isso ainda **não existe**.
5. **Sensores.** O comando de instalação e o `api_url` dos sensores passam a usar o endereço com HTTPS. Isso também resolve o aviso de texto original em HTTP do teste.

Ordem sugerida: domínio, HTTPS no servidor de teste, login OIDC real, só depois subdomínio por cliente.

## Executável assinado

Hoje o sensor é um `.pyz` (Python). Para o cliente instalar sem aviso do Windows e sem Python, o caminho é:

1. **Empacotar** com PyInstaller (ou similar) num runner `windows-latest` do CI, gerando `promptshield-sensor.exe`. Ainda não existe esse job.
2. **Comprar um certificado de assinatura de código** (Authenticode). Opções:
   - OV (validação da empresa): mais barato, exige CNPJ validado. Desde 2023 as autoridades exigem que a chave fique em dispositivo protegido (token ou HSM), então a assinatura costuma ser feita num token USB ou num serviço de assinatura na nuvem.
   - EV: mais caro, reputação imediata no SmartScreen em teoria; as regras mudaram, **A VERIFICAR**.
   - Serviço de assinatura gerenciado da Microsoft (Trusted Signing / Artifact Signing): existe a opção, mas disponibilidade por país e nome atual **A VERIFICAR**.
3. **Assinar no CI** com `signtool sign /fd SHA256 /tr <servidor de carimbo de tempo> /td SHA256 arquivo.exe`. Sempre com carimbo de tempo, para a assinatura valer depois que o certificado expirar. A chave nunca vai para o repositório: só como segredo do CI ou no serviço de assinatura.
4. **Publicar o hash** (SHA-256) no manifesto que o servidor já serve, e o `.exe` assinado no lugar do `.pyz`.
5. **macOS** (se houver Mac): Apple Developer Program (cerca de US$ 99 por ano), certificado "Developer ID" e notarização. **A VERIFICAR**.

Realidade do dia a dia: arquivos feitos com PyInstaller costumam gerar falso positivo em antivírus, mesmo assinados. Em empresa com TI, o caminho mais confiável é o administrador implantar por Intune ou GPO, e o certificado da sua empresa entrar na lista de editores confiáveis.

Custo e tempo: o certificado leva dias a semanas de validação do CNPJ. Não vale comprar antes de ter o primeiro cliente real; até lá, o instalador `.pyz` com SHA-256 serve para testes.
