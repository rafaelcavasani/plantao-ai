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

**Por quê?** Não dependemos de aprovação da Meta; controle total do webhooks; a mesma interface funciona local e em produção com seu próprio hardware.

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
$instance = "rafael"
$evolutionApiKey = "429683C4C977415CAAFCCE10F7D57E11"

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
$instance = "rafael"
$webhookUrl = "http://localhost:8000/webhooks/whatsapp"  # sua API, não Evolution
$webhookSecret = "UWAEmLaO8hDpM--c1pD1kSgT9q8gThU-WcxVrzzr7cGL8OAgqe8uRY6FPJoCX-cs"

$body = @{
    webhook = @{
        enabled = 1
        url = $webhookUrl
        headers = @{
            "X-Webhook-Token" = $webhookSecret
        }
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

## 11. Teste sem número de telefone (apenas webhook)

Se você quer testar a integração webhook **sem conectar um número de WhatsApp real** (útil para CI/CD, testes de
desenvolvimento isolados ou demonstrações), há dois caminhos:

### 11.1 Caminho A: Simular mandatórios da Evolution via cURL/script

Crie a instância normalmente, mas **não escaneie o QR code**. A Evolution aceita chamadas à API mesmo sem
conexão ativa. A Plantão.AI não valida essa condição no webhook, apenas na `readiness` check.

#### 11.1.1 Criar instância (sem QR)

```powershell
$instance = "test-instance"
$evolutionApiKey = "429683C4C977415CAAFCCE10F7D57E11"

$body = @{
    instanceName = $instance
} | ConvertTo-Json

$response = curl -X POST http://localhost:8080/instance/create `
  -H "Content-Type: application/json" `
  -H "apikey: $evolutionApiKey" `
  -d $body

$apiKey = ($response | ConvertFrom-Json).instance.apiKeys[0].apiKey
Write-Host "API Key da instância: $apiKey"
```

**Não escaneie o QR code.**

#### 11.1.2 Registrar webhook na instância

```powershell
$instance = "test-instance"
$webhookUrl = "http://localhost:8000/webhooks/whatsapp"
$webhookSecret = "UWAEmLaO8hDpM--c1pD1kSgT9q8gThU-WcxVrzzr7cGL8OAgqe8uRY6FPJoCX-cs"

$body = @{
    webhook = @{
        enabled = 1
        url = $webhookUrl
        headers = @{
            "X-Webhook-Token" = $webhookSecret
        }
    }
} | ConvertTo-Json

curl -X POST "http://localhost:8080/webhook/set/$instance" `
  -H "Content-Type: application/json" `
  -H "apikey: $evolutionApiKey" `
  -d $body

Write-Host "Webhook registrado para $webhookUrl"
```

#### 11.1.3 Simular mensagem manualmente via curl

A Evolution API **não possui endpoint nativo para simular mensagens de entrada**, mas você pode enviar webhooks
diretamente para sua aplicação (simulando o que Evolution faria):

```powershell
# Script PowerShell: test-webhook.ps1
# Simula um webhook de mensagem recebida

param(
    [string]$InstanceName = "test-instance",
    [string]$WebhookSecret = "UWAEmLaO8hDpM--c1pD1kSgT9q8gThU-WcxVrzzr7cGL8OAgqe8uRY6FPJoCX-cs",
    [string]$WebhookUrl = "http://localhost:8000/webhooks/whatsapp",
    [string]$Message = "Olá, qual o horário de funcionamento?",
    [string]$FromNumber = "5585999999999"  # simulate incoming number
)

# Payload conforme Evolution API especifica
$payload = @{
    event = "messages.upsert"
    instance = $InstanceName
    data = @{
        key = @{
            remoteJid = "${FromNumber}@s.whatsapp.net"
            fromMe = $false
            id = [guid]::NewGuid().ToString()
        }
        message = @{
            conversation = $Message
        }
    }
} | ConvertTo-Json -Depth 10

Write-Host "Enviando webhook para $WebhookUrl"
Write-Host "Payload:`n$payload`n"

$response = curl -X POST $WebhookUrl `
  -H "Content-Type: application/json" `
  -H "X-Webhook-Token: $WebhookSecret" `
  -d $payload `
  -v

Write-Host "Resposta:"
Write-Host $response

# Verificar logs no worker para ver se processou
Write-Host "`nVerifique os logs do worker (Terminal 2) para ver o processamento do job."
```

Executar:

```powershell
# Terminal (com venv ativado)
.\test-webhook.ps1

# Ou com parâmetros customizados:
.\test-webhook.ps1 -InstanceName rafael -Message "Qual o preço?" -FromNumber "5585988776655"
```

**O que acontece:**
1. Webhook chega na API (`POST /webhooks/whatsapp`)
2. API autentica com `X-Webhook-Token` (sem chamar Evolution)
3. API persiste e enfileira job `processar_mensagem`
4. Worker pega job, executa Roteador → Suporte → Resposta
5. Worker tenta enviar resposta via Evolution: `POST /message/sendText/test-instance`
   - Se a instância não está conectada, Evolution retorna erro (ex: status "close")
   - Job falha e fica registrado em `messages.status_envio = falha`
   - **Mas a conversa, intenção e resposta gerada já foram gravadas no banco**

**Verificar no banco:**

```sql
-- Conectar como administrador ou tenant_session ativo
SELECT correlation_id, remetente, conteudo, status_envio, intencao
  FROM messages
  WHERE tenant_id = (SELECT id FROM tenants WHERE slug = 'rafael')
  ORDER BY criado_em DESC
  LIMIT 5;
```

### 11.2 Caminho B: Mockar a Evolution inteira (para testes unitários/CI)

Se você quer um teste **completamente isolado** sem nenhuma dependência (nem Evolution, nem dados reais no
banco), usando pytest + mocking:

#### 11.2.1 Script de teste (Python)

Criar arquivo `tests/test_webhook_mock.py`:

```python
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch
import pytest

from apps.api.webhooks.whatsapp import ProcessarMensagemRequest


@pytest.mark.asyncio
async def test_webhook_without_evolution():
    """Testa webhook de chegada sem conectar Evolution ou WhatsApp real."""

    # Simular payload de Evolution
    webhook_payload = {
        "events": [
            {
                "event": "messages.upsert",
                "instance": "rafael",
                "data": {
                    "messages": [
                        {
                            "key": {
                                "remoteJid": "5585998765432@s.whatsapp.net",
                                "fromMe": False,
                                "id": "3EB0605AF8B15CD4D15A26FFB3E5A6C8",
                            },
                            "messageTimestamp": int(datetime.utcnow().timestamp()),
                            "pushName": "João Silva",
                            "status": "PENDING",
                            "message": {
                                "conversation": "Qual é o horário de funcionamento?"
                            },
                        }
                    ]
                },
            }
        ]
    }

    # Mock da API do Plantão (endpoint webhook)
    from fastapi.testclient import TestClient
    from apps.api.main import app

    client = TestClient(app)

    # Mock do redis (enfileiramento)
    with patch("apps.api.webhooks.whatsapp.enqueue") as mock_enqueue:
        mock_enqueue.return_value = AsyncMock()

        response = client.post(
            "/webhooks/whatsapp",
            json=webhook_payload,
            headers={"X-Webhook-Token": "UWAEmLaO8hDpM--c1pD1kSgT9q8gThU-WcxVrzzr7cGL8OAgqe8uRY6FPJoCX-cs"},
        )

        assert response.status_code == 200
        assert mock_enqueue.called

    # Opcional: verificar que mensagem foi persistida
    # session.query(Message).filter_by(instance="rafael").one()
```

Executar:

```powershell
pytest tests/test_webhook_mock.py -v
```

### 11.3 Caminho C: Docker mock da Evolution (container fake)

Se você quer um container que simula a Evolution sem instalar a real:

Criar `Dockerfile.evolution-mock`:

```dockerfile
FROM python:3.11-slim
RUN pip install fastapi uvicorn
COPY <<'EOF' /app.py
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/instance/create")
async def create_instance(body: dict, headers: dict = None):
    instance_name = body.get("instanceName", "unknown")
    return {
        "instance": {
            "instanceName": instance_name,
            "status": "created",
            "qrcode": None,
            "apiKeys": [
                {"apiKey": "mock-api-key-12345", "name": "padrão"}
            ]
        }
    }

@app.get("/instance/connectionState/{instance_name}")
async def connection_state(instance_name: str):
    # Simular instancia aberta mas sem realmente estar conectada
    return {"instance": {"state": "closed"}}

@app.get("/instance/connect/{instance_name}")
async def connect(instance_name: str):
    return {"qrcode": "mock-base64-encoded-qr-code"}

@app.post("/webhook/set/{instance_name}")
async def set_webhook(instance_name: str, body: dict):
    return {"status": "ok", "webhook": body.get("webhook")}

@app.post("/message/sendText/{instance_name}")
async def send_text(instance_name: str, body: dict):
    # Mock de envio bem-sucedido
    return {
        "status": "success",
        "messageId": "mock-message-id-123"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
EOF
WORKDIR /
CMD ["python", "/app.py"]
```

Subir:

```powershell
docker build -f Dockerfile.evolution-mock -t evolution-mock:latest .
docker run -d -p 8080:8080 --name evolution-mock evolution-mock:latest

# Testar
curl http://localhost:8080/health
```

### 11.4 Resumo: qual caminho escolher?

| Caminho | Caso de Uso | Setup | Realismo | Velocidade |
|---|---|---|---|---|
| **A (cURL manual)** | Dev local, debug rápido | Mínimo (só curl) | Alto | Rápido |
| **B (pytest mock)** | CI/CD, testes de integração | Médio (pytest + conftest) | Médio | Muito rápido |
| **C (Evolution mock)** | Dev isolado, sem internet | Médio (Docker) | Baixo | Rápido |

**Recomendação para desenvolvimento:**
1. Use o **Caminho A** (cuRL manual) enquanto desenvolve features localmente
2. Integre o **Caminho B** (pytest) no seu CI para validações automáticas
3. Use **Caminho C** apenas se a Evolution inteira ficar indisponível

## 11. Referências

- [README.md: stack e diagramas](../README.md)
- [ADR-0003: como a empresa é resolvida](adr/0003-resolucao-por-conexao.md)
- [Contract: whatsapp-webhook.md](../specs/002-multitenancy/contracts/whatsapp-webhook.md)
- [contract: channel-port.md](../specs/002-multitenancy/contracts/channel-port.md)
- [RUNBOOK_OPERACIONAL.md: onboarding completo](RUNBOOK_OPERACIONAL.md)
- Evolution API docs: https://evolution-api.com/docs
