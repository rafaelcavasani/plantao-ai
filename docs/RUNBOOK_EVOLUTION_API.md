# Runbook: Evolution API + Plantão.AI

Conecta agente ao WhatsApp via Evolution API (self-hosted). Aplicação resolve empresa pelo `instance_name`,
autentica por `X-Webhook-Token` por conexão, e envia por `POST /message/sendText/{instance}`. Diagrama em
[README.md](../README.md#1-visão-geral-e-integrações); design em [ADR-0003](adr/0003-resolucao-por-conexao.md).

## 1. O que é Evolution API

Wrapper de código aberto para o WhatsApp Business API. Você:
- hospeda a instância na sua infraestrutura
- cria conexões (instâncias) para cada conta de WhatsApp
- valida a conta com QR code
- integra à sua aplicação por REST

- Repo: https://github.com/EvolutionAPI/evolution-api
- Docs: https://evolution-api.com/docs

**Por quê?** Não dependemos de aprovação da Meta; controle total do webhooks; a mesma interface funciona local e em
produção com seu próprio hardware.

## 2. Infraestrutura local (MVP)

Rodamos Evolution na máquina de desenvolvimento com Docker. Necessário:

```powershell
# Verificar Docker + docker-compose
docker --version
docker-compose --version

# Estrutura recomendada
mkdir evolution-local
cd evolution-local
```

### 2.1 Arquivo docker-compose para Evolution

Criar `evolution-docker-compose.yml` (ou adicionar ao seu `docker-compose.yml` no projeto):

```yaml
version: '3.8'
services:
  evolution:
    image: evolutionapi/evolution:latest
    container_name: evolution-api
    restart: unless-stopped
    environment:
      # CONFIG
      EVOLUTION_CONTAINER_NAME: evolution
      EVOLUTION_API_KEY: sua-chave-api-super-secreta
      EVOLUTION_API_URL_BASE: "http://localhost:8080"
      EVOLUTION_LOG_LEVEL: "INFO"
      EVOLUTION_SAVE_DATA_ON_SYNC: "true"
      
      # Banco (opcional; sem isso usa arquivo local)
      # DATABASE_CONNECTION_URI: "postgresql://user:pass@postgres:5432/evolution"
    ports:
      - "8080:8080"
    volumes:
      - evolution_data:/Evolution/instances
      - evolution_storage:/Evolution/store
    networks:
      - plantao-network

volumes:
  evolution_data:
  evolution_storage:

networks:
  plantao-network:
    driver: bridge
```

Subir:

```powershell
docker-compose -f evolution-docker-compose.yml up -d
docker-compose -f evolution-docker-compose.yml logs -f evolution
# Verificar: GET http://localhost:8080/health
```

Deve responder algo como `{"status":"ok"}` ou similar (formato varia entre versões).

### 2.2 Variáveis de ambiente

No `.env` da aplicação (Plantão.AI):

```dotenv
WHATSAPP_PROVIDER=evolution
WHATSAPP_BASE_URL=http://localhost:8080
WHATSAPP_VERIFY_TOKEN=change-me   # usado só pela Meta Cloud API, não por Evolution
```

Ou em produção, se Evolution está em outro host:

```dotenv
WHATSAPP_BASE_URL=https://evolution.sua-empresa.com
```

## 3. Criar instância e obter credenciais

### 3.1 Criar instância (cria o espaço para a empresa)

A instância recebe um nome único; é o `instance_name` do arquivo de onboarding.

```powershell
$instance = "clinica-sorriso"
$evolutionApiKey = "sua-chave-api-super-secreta"

# POST /instance/create
$body = @{
    instanceName = $instance
} | ConvertTo-Json

$response = curl -X POST http://localhost:8080/instance/create `
  -H "Content-Type: application/json" `
  -H "apikey: $evolutionApiKey" `
  -d $body

$response | ConvertFrom-Json | ConvertTo-Json -Depth 10
```

Resposta esperada:

```json
{
  "instance": {
    "instanceName": "clinica-sorriso",
    "status": "created",
    "qrcode": null,
    "apiKeys": [
      {
        "apiKey": "**COPIAR ESTE VALOR**",
        "name": "padrão"
      }
    ]
  }
}
```

**Guardar:**
- `apiKey` → será `$env:CLINICA_SORRISO_EVOLUTION_API_KEY`

### 3.2 Conectar conta WhatsApp

A Evolution fornece um QR code que você escaneia com o celular (WhatsApp anexado a uma conta Business).

```powershell
$instance = "clinica-sorriso"

# GET /instance/connect/{instance}
curl -X GET "http://localhost:8080/instance/connect/$instance" `
  -H "apikey: $evolutionApiKey"
```

Resposta: um JSON com campo `qrcode` (string base64 ou URL). Exibir o QR code no terminal ou salvar como PNG:

```powershell
# Se recebeu URL, abrir no navegador:
# http://localhost:8080/instance/qrcode/clinica-sorriso

# Ou baixar como arquivo:
curl -X GET "http://localhost:8080/instance/qrcode/$instance" `
  -H "apikey: $evolutionApiKey" `
  -o qrcode.png

# Escanear com celular que tem a conta de WhatsApp Business
```

Após escanear:
- Celular recebe uma notificação de "nova sessão"
- Evolution reconhece e muda o estado para "open"
- Instância está pronta para enviar/receber

Verificar status:

```powershell
curl -X GET "http://localhost:8080/instance/connectionState/$instance" `
  -H "apikey: $evolutionApiKey"

# Resposta:
# {"instance":{"state":"open"}} ou {"instance":{"state":"close"}}
```

## 4. Registrar webhook na Evolution

Toda mensagem recebida no WhatsApp é entregue à sua aplicação por um webhook HTTP. A Evolution precisa saber
aonde mandar.

```powershell
$instance = "clinica-sorriso"
$webhookUrl = "http://localhost:3000/webhooks/whatsapp"  # sua API, não Evolution
$webhookSecret = "seu-segredo-de-webhook-min-32-caracteres-aqui"

$body = @{
    url = $webhookUrl
    headers = @{
        "X-Webhook-Token" = $webhookSecret
    }
} | ConvertTo-Json

curl -X POST "http://localhost:8080/webhook/set/$instance" `
  -H "Content-Type: application/json" `
  -H "apikey: $evolutionApiKey" `
  -d $body
```

**Recomendação:** use `$webhook_secret` com pelo menos 32 caracteres e caracteres especiais (exigência de
validação da aplicação).

```powershell
# Gerar um segredo robusto:
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Copiar a saída e colar no comando acima
```

Verificar:

```powershell
curl -X GET "http://localhost:8080/webhook/find/$instance" `
  -H "apikey: $evolutionApiKey"

# Resposta: lista de webhooks registrados
```

## 5. Configurar o arquivo de onboarding da empresa

Arquivo: `docs/exemplos/clinica-sorriso.yml` (ou seu campo `slug`):

```yaml
slug: clinica-sorriso
nome_empresa: "Clínica Sorriso"
nicho: clinica_odontologica
plano: recepcionista

canal:
  tipo: whatsapp
  provedor: evolution
  instance_name: clinica-sorriso      # IGUAL ao da Evolution
  api_key_env: CLINICA_SORRISO_EVOLUTION_API_KEY
  webhook_secret_env: CLINICA_SORRISO_WEBHOOK_SECRET
```

Salvar os segredos em variáveis de ambiente:

```powershell
# Antes de rodar o `tenants create`

# Da seção 3.1 (criação de instância)
$env:CLINICA_SORRISO_EVOLUTION_API_KEY = "...colar da resposta..."

# Do seção 4 (webhook)
$env:CLINICA_SORRISO_WEBHOOK_SECRET = "seu-segredo-de-webhook-min-32-caracteres-aqui"

# Ou para sessão permanente, adicionar a `$PROFILE`:
Add-Content $PROFILE @"
`$env:CLINICA_SORRISO_EVOLUTION_API_KEY = "valor"
`$env:CLINICA_SORRISO_WEBHOOK_SECRET = "valor"
"@
```

## 6. Onboarding da empresa

```powershell
# (venv ativado)
python -m scripts.tenants create --file docs/exemplos/clinica-sorriso.yml --operador rafael
python -m scripts.tenants readiness clinica-sorriso --operador rafael
python -m scripts.tenants test clinica-sorriso --file docs/exemplos/clinica-sorriso.yml --operador rafael
python -m scripts.tenants activate clinica-sorriso --operador rafael
```

Neste ponto, a aplicação conhece a conexão e suas credenciais.

## 7. Testar ponta a ponta

### 7.1 Subir a aplicação

Terminal 1: API

```powershell
make api
```

Terminal 2: worker

```powershell
make worker
```

### 7.2 Enviar uma mensagem de teste

Abra o chatsapp da continha que está anexada na Evolution. Eoscreva para o número de WhatsApp Business da
clínica:

```
Olá, qual o horário de funcionamento?
```

### 7.3 Checar o que aconteceu

No worker (terminal 2):
- Deve logar `mensaje_enfileirada` com `tenant_id` da clínica e `correlation_id`
- Grafo roda (Roteador → Suporte → Guardrails → Resposta)
- Resposta sai por `POST /message/sendText/clinica-sorriso`

Na Evolution:
- Logs indicam entrega para WhatsApp

No WhatsApp:
- Mensagem de resposta chega em 5-30 segundos

No Postgres (verificar com `psql`):
```sql
-- (ativar tenant_session ou usar papel admin)
SELECT correlation_id, remetente, conteudo, status_envio
  FROM messages
  WHERE tenant_id = (SELECT id FROM tenants WHERE slug = 'clinica-sorriso')
  ORDER BY criado_em DESC
  LIMIT 3;
```

## 8. Verificar conexão

Qualquer hora, testar se a instância está conectada:

```powershell
python -m scripts.tenants readiness clinica-sorriso --operador rafael
```

Campo `conexao verificada`: se `OK`, está online; senão, QR code expirou ou celular desconectou.

Reconectar:

```powershell
# GET /instance/connect/{instance} para novo QR code
curl -X GET "http://localhost:8080/instance/connect/clinica-sorriso" `
  -H "apikey: $evolutionApiKey"
# Escanear de novo
```

## 9. Cenários e troubleshooting

| Sintoma | Causa | Solução |
|---|---|---|
| Webhook retorna `401` | Token errado, instance desconhecida, Evolution não configurada | Verificar `instance_name`, `X-Webhook-Token` no header da Evolution, `WHATSAPP_BASE_URL` no `.env` |
| Evolution responde `{"status": "close"}` | QR code expirou | Resgatar novo QR, escanear de novo |
| API recebe webhook mas não enfileira | Empresa não ativa, estado não é `ativo` | `tenants activate <slug>` e repetir teste |
| Resposta demora > 30s ou não sai | Worker morreu ou grafo travou | Verificar logs do worker; reiniciar com `make worker` |
| "apikey" é inválido na Evolution | Chave copiada errada ou da instância errada | Recriar instância (`/instance/create`) e copiar `apiKey` novamente |
| Mensagem entra mas guardrail bloqueia | Palavra-gatilho configurada errada | Usar `tenants config show <slug>` e ajustar com `config set` |
| Numero bloqueado no WhatsApp | Muitos webhooks ou teste de spam | Aguardar 24h; trocar de numero para testes seguintes |

## 10. Produção

### Infraestrutura Evolution

- Self-hosted em VM ou container (K8s, Docker Swarm, etc.)
- Banco de dados Postgres (Evolution suporta) em vez de arquivo local
- HTTPS (certificado Let's Encrypt ou similar)
- Backup de volumes `evolution_data` e `evolution_storage`
- Monitoramento de `GET /health` e taxa de erro de webhook

### Plantão.AI

- `WHATSAPP_BASE_URL` aponta para URL HTTPS da Evolution
- Cada empresa tem seu `instance_name`, `api_key_env`, `webhook_secret_env` (nomes de variáveis, valores em
  Vault ou Secrets Manager)
- Webhook de entrada é HTTPS (certificado)
- Observar `llm_calls`, `handoff_log` e `audit_log` em Postgres (telemetria/alertas)
- Rate limit por empresa em Redis (`rl:{tenant_id}:...`) isolado entre empresas

### Segredos

- **Nunca** versionem `EVOLUTION_API_KEY` ou `WHATSAPP_*` (usar gerenciador de segredos)
- Webhook secret ≥ 32 caracteres, aleatório
- Logs mascarados: telefone, conteúdo, tokens/chaves nunca impressas (garantido pela aplicação)
- `DATABASE_ADMIN_URL` nunca usado em container públicos; papel administrativo só em máquinas exclusivas de script

## 11. Referências

- [README.md: stack e diagramas](../README.md)
- [ADR-0003: como a empresa é resolvida](adr/0003-resolucao-por-conexao.md)
- [Contract: whatsapp-webhook.md](../specs/002-multitenancy/contracts/whatsapp-webhook.md)
- [contract: channel-port.md](../specs/002-multitenancy/contracts/channel-port.md)
- [RUNBOOK_OPERACIONAL.md: onboarding completo](RUNBOOK_OPERACIONAL.md)
- Evolution API docs: https://evolution-api.com/docs
