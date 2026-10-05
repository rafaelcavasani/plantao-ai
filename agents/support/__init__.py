"""Agente de Suporte — respostas via RAG. Implementação prevista para o Sprint 2.

Guardrail principal: se a pergunta não tem resposta na base de
conhecimento do tenant com confiança suficiente, nunca "chutar" — deve
escalar para handoff humano (ver seção 8.4).
"""
