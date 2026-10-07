# Verificações do front-end do painel em navegador (opcional)

Duas verificações complementam os testes do projeto (`make test-web`, pytest). Elas **não fazem parte do CI** e as
dependências delas não entram no projeto (constituição, princípio VIII): instale numa pasta à parte.

| Script | O que prova | Precisa de |
|---|---|---|
| `fumaca-jsdom.mjs` | os módulos reais do front contra a API real: login, visão geral, empresas, ficha, suspender e retomar, encerrar com nome exato, cadastro com validação, edição, conversas, sessão inválida | `jsdom` |
| `navegador-real.mjs` | em Chrome de verdade: CSP sem violação, axe-core WCAG 2.1 AA, sem rolagem horizontal a 390/768/1000 px, KPIs em 4/2/1 colunas, menu do celular, foco preso na janela, `Esc`, movimento reduzido, fontes carregadas, nenhum "null" visível, rótulos do gráfico sem sobreposição | `playwright-core`, `axe-core`, Chrome |

## Como rodar

```powershell
# 1. dependências só desta pasta (node_modules fica fora do git; nada entra em package.json do projeto)
npm install --prefix scripts/painel_e2e --no-save --no-package-lock jsdom@22 playwright-core@1.48 axe-core

# 2. banco de teste com 3 empresas (da raiz do repositório)
python scripts/painel_e2e/semear.py

# 3. API de desenvolvimento apontando para o banco de teste (outra porta)
$env:ENV="development"; $env:PAINEL_AUTH_MODE="dev"; $env:OIDC_ISSUER=""
$env:OPERADORES="ana@exemplo.com:operacao,leitor@exemplo.com:leitura"
$env:DATABASE_URL="postgresql+asyncpg://plantao_app:plantao_app@localhost:5432/plantao_test"
$env:DATABASE_ADMIN_URL="postgresql+asyncpg://plantao:plantao@localhost:5432/plantao_test"
$env:DATABASE_PAINEL_URL="postgresql+asyncpg://plantao_painel:plantao_painel@localhost:5432/plantao_test"
python -m uvicorn apps.api.main:app --port 8767

# 4. verificações (em outro terminal, da raiz do repositório)
$env:PAINEL_BASE="http://127.0.0.1:8767"
node scripts/painel_e2e/fumaca-jsdom.mjs
node scripts/painel_e2e/navegador-real.mjs   # CHROME=<caminho> se o Chrome não estiver no local padrão; PAINEL_PRINTS=<pasta> guarda os prints
```

Os dois scripts usam o login de desenvolvimento (`PAINEL_AUTH_MODE=dev`), que só funciona com `ENV=development`.
Rode a `fumaca-jsdom.mjs` logo após a `semear.py` (ela cria empresas com os mesmos nomes).
