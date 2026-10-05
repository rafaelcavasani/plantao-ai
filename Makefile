# Comandos principais do Plantão.AI. Execute a partir de plantao-ai/.
# Funciona no Windows (cmd/PowerShell com make do Chocolatey) e em Linux/macOS.

ifeq ($(OS),Windows_NT)
BIN := .venv\Scripts
PY  := .venv\Scripts\python.exe
else
BIN := .venv/bin
PY  := .venv/bin/python
endif

# Pasta com os documentos a indexar, usada por `make ingest`.
DOCS ?= tests/evals/docs_piloto
# Empresa (slug) dos comandos de operador; operador que executa; arquivo de onboarding.
TENANT ?=
OPERADOR ?=
FILE ?=
# Motivo opcional de `make tenant-suspend` e `make tenant-close` (vai para a auditoria).
MOTIVO ?=
# Nome exato da empresa, exigido por `make tenant-purge` (confirmação).
CONFIRMAR ?=
# Nome do documento, usado por `make ingest-remove`.
NOME ?=
# Mensagem da migração, usada por `make migration`.
MSG  ?= nova migracao
# Suíte do run_evals: todas ou o nome de uma suíte.
SUITE ?= todas

.DEFAULT_GOAL := help

.PHONY: help venv install up down reset-db migrate migration ingest ingest-list \
	ingest-remove tenant-create tenant-list tenant-status tenant-readiness tenant-test tenant-activate tenant-suspend tenant-resume tenant-close tenant-purge api worker test test-unit test-integration test-adversarial cov \
	lint format typecheck imports audit check evals

help:
	@echo Ambiente
	@echo   make venv              cria o .venv
	@echo   make install           instala requirements-dev.txt
	@echo Infraestrutura
	@echo   make up                sobe Postgres e Redis
	@echo   make down              derruba os containers
	@echo   make reset-db          apaga volumes, sobe de novo e aplica migracoes
	@echo Banco e dados
	@echo   make migrate           alembic upgrade head
	@echo   make migration MSG=x   gera migracao autogenerate
	@echo   make ingest TENANT=slug       carrega DOCS na empresa
	@echo   make ingest-list TENANT=slug  lista documentos
	@echo   make ingest-remove TENANT=slug NOME=arquivo.md
	@echo Empresas
	@echo   make tenant-create FILE=empresa.yml OPERADOR=nome
	@echo   make tenant-list
	@echo   make tenant-status TENANT=slug
	@echo   make tenant-readiness TENANT=slug OPERADOR=nome
	@echo   make tenant-test TENANT=slug FILE=empresa.yml OPERADOR=nome
	@echo   make tenant-activate TENANT=slug OPERADOR=nome
	@echo   make tenant-suspend TENANT=slug OPERADOR=nome [MOTIVO=texto]
	@echo   make tenant-resume TENANT=slug OPERADOR=nome
	@echo   make tenant-close TENANT=slug OPERADOR=nome [MOTIVO=texto]
	@echo   make tenant-purge TENANT=slug OPERADOR=nome CONFIRMAR="Nome da Empresa"
	@echo Execucao
	@echo   make api               uvicorn com reload na porta 8000
	@echo   make worker            worker arq
	@echo Testes e qualidade
	@echo   make test              suite completa
	@echo   make test-unit         sem Postgres nem Redis
	@echo   make test-integration  exige docker compose
	@echo   make test-adversarial  suite adversarial
	@echo   make cov               cobertura, 80 por cento total e 100 por cento em guardrails
	@echo   make lint              ruff check e format --check
	@echo   make format            ruff format e check --fix
	@echo   make typecheck         mypy estrito
	@echo   make imports           contratos do import-linter
	@echo   make audit             pip-audit
	@echo   make check             lint, typecheck, imports, cov e audit
	@echo   make evals TENANT=slug  avaliacao com LLM real, usa creditos. SUITE=todas

venv:
	python -m venv .venv

install:
	$(PY) -m pip install -r requirements-dev.txt

up:
	docker compose up -d

down:
	docker compose down

reset-db:
	docker compose down -v
	docker compose up -d
	$(MAKE) migrate

migrate:
	$(PY) -m alembic upgrade head

migration:
	$(PY) -m alembic revision --autogenerate -m "$(MSG)"

tenant-create:
	$(PY) -m scripts.tenants create --file $(FILE) --operador $(OPERADOR)

tenant-list:
	$(PY) -m scripts.tenants list

tenant-status:
	$(PY) -m scripts.tenants status $(TENANT)

tenant-readiness:
	$(PY) -m scripts.tenants readiness $(TENANT) --operador $(OPERADOR)

tenant-test:
	$(PY) -m scripts.tenants test $(TENANT) --file $(FILE) --operador $(OPERADOR)

tenant-activate:
	$(PY) -m scripts.tenants activate $(TENANT) --operador $(OPERADOR)

tenant-suspend:
	$(PY) -m scripts.tenants suspend $(TENANT) --operador $(OPERADOR) $(if $(MOTIVO),--motivo "$(MOTIVO)")

tenant-resume:
	$(PY) -m scripts.tenants resume $(TENANT) --operador $(OPERADOR)

tenant-close:
	$(PY) -m scripts.tenants close $(TENANT) --operador $(OPERADOR) $(if $(MOTIVO),--motivo "$(MOTIVO)")

tenant-purge:
	$(PY) -m scripts.tenants purge $(TENANT) --operador $(OPERADOR) --confirmar "$(CONFIRMAR)"

ingest:
	$(PY) -m scripts.ingest_docs load --tenant $(TENANT) $(DOCS)

ingest-list:
	$(PY) -m scripts.ingest_docs list --tenant $(TENANT)

ingest-remove:
	$(PY) -m scripts.ingest_docs remove --tenant $(TENANT) $(NOME) --yes

api:
	$(PY) -m uvicorn apps.api.main:app --reload --port 8000

worker:
	$(PY) -m arq apps.worker.settings.WorkerSettings

test:
	$(PY) -m pytest -q

test-unit:
	$(PY) -m pytest -q tests/unit

test-integration:
	$(PY) -m pytest -q tests/integration

test-adversarial:
	$(PY) -m pytest -q tests/adversarial

cov:
	$(PY) -m pytest -q --cov --cov-report=term-missing
	$(PY) -m coverage report --include="core/guardrails/*" --fail-under=100

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:
	$(PY) -m ruff check . --fix
	$(PY) -m ruff format .

typecheck:
	$(PY) -m mypy

imports:
	$(BIN)/lint-imports

audit:
	$(PY) -m pip_audit

check: lint typecheck imports cov audit

evals:
	$(PY) -m scripts.run_evals --tenant $(TENANT) --suite $(SUITE)
