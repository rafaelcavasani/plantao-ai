"""Painel de operação das empresas (spec 004, ADR-0005).

O front-end é estático e mora em `web/` (HTML, CSS e módulos ES, sem build). A API o serve em `/painel/` e ele só
fala com `/admin/*` (`apps/api/admin`). Não há código Python do painel aqui: a regra e as consultas ficam em
`core/painel`.
"""
