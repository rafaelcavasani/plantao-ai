"""Workers assíncronos (fila Redis) — processamento fora do ciclo request/response.

Implementação prevista a partir do Sprint 4 (régua de lembretes de
agendamento e cobrança). Por enquanto, todo o processamento do Sprint 1-3
roda de forma síncrona dentro do próprio handler do webhook.
"""
