# Script PowerShell: test-webhook.ps1
# Simula um webhook de mensagem recebida pela Evolution API
# Uso: .\test-webhook.ps1 -InstanceName web-mock -Message "Olá" -FromNumber "5585999999999"

param(
    [string]$InstanceName = "web-mock",
    [string]$WebhookSecret = "UWAEmLaO8hDpM--c1pD1kSgT9q8gThU-WcxVrzzr7cGL8OAgqe8uRY6FPJoCX",
    [string]$WebhookUrl = "http://localhost:8000/webhooks/whatsapp",
    [string]$Message = "Olá, qual o horário de funcionamento?",
    [string]$FromNumber = "5585999999999"  # simulate incoming number
)

# Payload conforme Evolution API especifica (contrato: specs/002-multitenancy/contracts/whatsapp-webhook.md)
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

Write-Host "======================================"
Write-Host "Enviando webhook simulado"
Write-Host "======================================"
Write-Host "URL: $WebhookUrl"
Write-Host "Instance: $InstanceName"
Write-Host "From: $FromNumber"
Write-Host "Message: $Message"
Write-Host "======================================`n"

try {
    $response = curl -X POST $WebhookUrl `
      -H "Content-Type: application/json" `
      -H "X-Webhook-Token: $WebhookSecret" `
      -d $payload `
      -s -w "`nHTTP Status: %{http_code}"

    Write-Host "Resposta da API:"
    Write-Host $response
    Write-Host "`n======================================`n"
    
    # Verificar logs no worker para ver se processou
    Write-Host "✓ Webhook enviado com sucesso!"
    Write-Host "`nVerifique os logs do worker (Terminal 2) para ver o processamento do job."
    Write-Host "Procure por:"
    Write-Host "  - 'roteador'"
    Write-Host "  - 'embedding'"
    Write-Host "  - 'suporte'"
    Write-Host "  - 'sendText'"
}
catch {
    Write-Host "✗ Erro ao enviar webhook: $_"
    exit 1
}
