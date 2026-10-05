# Sprint 1 — Fundação (detalhamento executável)

> Granularização da entrega "Sprint 1 — Fundação" da seção 8.7 de [Projeto_Empresa_Autonoma.md](../../Projeto_Empresa_Autonoma.md).
> Objetivo do sprint: ter um webhook do WhatsApp recebendo mensagens reais e ecoando de volta, com toda a infraestrutura de base funcionando — **ainda sem nenhuma inteligência de agente**.

## Checklist

- [x] Estrutura de pastas do repositório criada (apps, agents, core, integrations, db, tests, scripts)
- [x] `docker-compose.yml` com Postgres (imagem `pgvector/pgvector`) e Redis
- [x] Configurações centrais via `pydantic-settings` ([core/config.py](../core/config.py))
- [x] Modelo de dados completo ([db/models.py](../db/models.py)) cobrindo as 10 entidades da seção 8.3
- [x] Script de bootstrap do schema ([scripts/init_db.py](../scripts/init_db.py)) — cria extensão `vector` + tabelas
- [x] Script de seed de um tenant de teste ([scripts/seed_tenant.py](../scripts/seed_tenant.py))
- [x] FastAPI básico com endpoint de health check
- [x] Webhook de WhatsApp (`POST /webhooks/whatsapp`) recebendo payload, persistindo mensagem e respondendo com eco
- [x] Endpoint de verificação de webhook (`GET /webhooks/whatsapp`) compatível com Meta Cloud API
- [x] Cliente de WhatsApp abstrato ([integrations/whatsapp/client.py](../integrations/whatsapp/client.py)) com implementação inicial para Evolution API
- [x] Esqueleto do orquestrador LangGraph ([core/orchestrator/graph.py](../core/orchestrator/graph.py)) com nós stub (roteador → guardrails → suporte/handoff)
- [x] Módulo de guardrails com checklist funcional e testado ([core/guardrails/checks.py](../core/guardrails/checks.py))
- [x] Testes automatizados (health check + guardrails)
- [ ] **Pendente (ação manual sua)**: subir uma instância da Evolution API (ou provedor equivalente) e conectar um número de WhatsApp de teste
- [ ] **Pendente (ação manual sua)**: rodar `python -m scripts.seed_tenant` para criar o primeiro tenant de teste
- [ ] **Pendente (ação manual sua)**: obter uma chave da OpenRouter e preencher o `.env`

## Como validar que o Sprint 1 está "pronto"

1. `docker compose up -d` sobe sem erros
2. `python -m scripts.init_db` cria as tabelas sem erros
3. `python -m scripts.seed_tenant` cria um tenant de teste
4. `uvicorn apps.api.main:app --reload` sobe e `GET /health` retorna `{"status": "ok", ...}`
5. Enviar um `POST` manual (ex.: via `curl`/Postman/Thunder Client) simulando o payload da Evolution API para `/webhooks/whatsapp` e ver a mensagem persistida no banco (`SELECT * FROM messages;`)
6. `pytest` passa sem falhas

### Exemplo de payload para testar o webhook manualmente

```json
{
  "data": {
    "key": { "remoteJid": "5511999999999@s.whatsapp.net" },
    "message": { "conversation": "Olá, qual o horário de vocês?" }
  }
}
```

```powershell
curl.exe -X POST http://localhost:8000/webhooks/whatsapp `
  -H "Content-Type: application/json" `
  -d '{\"data\":{\"key\":{\"remoteJid\":\"5511999999999@s.whatsapp.net\"},\"message\":{\"conversation\":\"Ola, qual o horario de voces?\"}}}'
```

## Próximo passo (Sprint 2)

Substituir o stub de [agents/router/agent.py](../agents/router/agent.py) por uma chamada real a um modelo via OpenRouter, e implementar o Agente de Suporte com busca RAG em `tenant_knowledge` — ver seção 8.4 da especificação em [Projeto_Empresa_Autonoma.md](../../Projeto_Empresa_Autonoma.md).
