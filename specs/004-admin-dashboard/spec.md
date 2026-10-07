# Feature Specification: Painel de operação de empresas (tenants)

**Feature Branch**: `004-admin-dashboard`

**Created**: 2026-10-06

**Status**: Draft

**Input**: User description: "Criar um front-end onde tenha o gerenciamento dos tenants, um dashboard com agregações e informações de cada tenant, como número de mensagens, status, última mensagem, etc."

Esta especificação continua a [002-multitenancy](../002-multitenancy/spec.md): hoje o operador gerencia empresas só pela linha de comando (`scripts/tenants.py`: `create`, `list`, `status`, `readiness`, `activate`, `suspend`, `resume`, `close`, `purge`, `config`, `audit`). O painel dá uma interface visual às mesmas operações e acrescenta o que a linha de comando não mostra: volume de atendimento, custo e saúde de cada empresa ao longo do tempo. Ele **não muda** as regras de ciclo de vida, de isolamento nem de atendimento; apenas as expõe.

## Clarifications

### Session 2026-10-06

- Q: O operador da plataforma pode ler o texto das mensagens dos clientes finais no painel, ou só metadados? → A: Só metadados (horário, remetente, tipo, intenção, motivo do handoff). Nenhum texto de mensagem e nenhum telefone, nem mascarado.
- Q: Com que atraso máximo os números do painel podem refletir a realidade? → A: Até 5 minutos, com botão "Atualizar".
- Q: Quais limites marcam uma empresa como "em atenção"? → A: 24 h sem mensagem (empresa ativa), handoff acima de 30% das conversas no período e custo em 90% ou mais do orçamento mensal; valores globais, alteráveis por configuração.
- Q: De onde vem o orçamento mensal de custo de cada empresa? → A: Derivado do plano: cada plano tem um valor de orçamento em configuração; não há campo de orçamento por empresa.
- Q: O painel mostra a margem estimada de cada empresa, cadastrando o preço mensal de cada plano? → A: Sim, preço por plano, na mesma tabela de planos do orçamento.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operador vê a saúde da carteira de empresas de relance (Priority: P1)

O operador abre o painel e, numa única tela, vê quantas empresas existem em cada estado, o volume de mensagens e conversas do período, quantas conversas estão esperando uma pessoa (handoff) e o custo total. Abaixo, uma tabela com uma linha por empresa mostra estado, mensagens no período, data e hora da última mensagem, conversas abertas, handoffs e custo.

**Why this priority**: É a pergunta central do pedido ("como estão meus clientes?") e hoje só se responde rodando comandos empresa por empresa. Entrega valor sozinha, sem nenhuma ação de escrita.

**Independent Test**: Com 3 empresas de teste em estados diferentes e mensagens conhecidas, abrir o painel e conferir que cada número da tela bate com a contagem feita direto na base, e que cada empresa aparece com o estado e a última mensagem corretos.

**Acceptance Scenarios**:

1. **Given** empresas nos quatro estados, **When** o operador abre a visão geral, **Then** vê o total por estado (em configuração, ativo, suspenso, encerrado) e o total de empresas.
2. **Given** um período selecionado (hoje, 7 dias, 30 dias), **When** o operador o troca, **Then** todos os totais e a tabela se recalculam para o período, e o período escolhido fica visível.
3. **Given** a tabela de empresas, **When** o operador ordena por mensagens, última mensagem ou custo, **Then** a ordem muda e se mantém ao atualizar a página.
4. **Given** uma empresa que nunca recebeu mensagem, **When** aparece na tabela, **Then** mostra "sem mensagens" na última mensagem e zero nos contadores, nunca um erro ou campo vazio.
5. **Given** uma empresa ativa sem mensagem há mais tempo que o limite de silêncio definido, **When** a tabela é exibida, **Then** ela recebe um sinal de atenção visível ("sem atividade").
6. **Given** a tabela com muitas empresas, **When** o operador busca por nome ou `slug` e filtra por estado ou nicho, **Then** só as correspondentes aparecem.

---

### User Story 2 - Operador investiga uma empresa em detalhe (Priority: P1)

O operador clica numa empresa e vê a ficha completa: identificação (nome, `slug`, nicho, plano), estado e datas (criada, ativada, encerrada), conexão do canal (instância, verificada em), documentos e trechos da base de conhecimento, última prontidão e último teste, e séries ao longo do tempo de mensagens, conversas, handoffs, custo e tokens, com a divisão por finalidade (roteador, suporte, embedding).

**Why this priority**: Visão geral sem detalhe não resolve incidente ("por que a clínica X parou de responder?"). Detalhe e visão geral juntos formam o núcleo da leitura; por isso ambas são P1.

**Independent Test**: Abrir a ficha de uma empresa com histórico conhecido e conferir que os números e gráficos batem com o que `tenants status` e a base mostram.

**Acceptance Scenarios**:

1. **Given** uma empresa, **When** o operador abre a ficha, **Then** vê os mesmos dados que `tenants status` mostra, mais as séries do período.
2. **Given** a ficha, **When** o operador olha o bloco de atendimento, **Then** vê mensagens recebidas e enviadas, conversas por status (aberta, handoff, resolvida), taxa de handoff, tempo médio de resposta e distribuição de intenções.
3. **Given** a ficha, **When** o operador olha o bloco de custo, **Then** vê custo e tokens por dia e por finalidade, custo por conversa e o total do período.
4. **Given** a ficha, **When** o operador abre o histórico de mudanças, **Then** vê as linhas de auditoria (estado, configuração, conexão) com quem fez, quando, valor anterior e novo, sem nunca exibir credenciais.
5. **Given** uma empresa encerrada com dados já apagados, **When** o operador abre a ficha, **Then** vê o cadastro e as datas, e os blocos de atendimento aparecem como "dados apagados em <data>".
6. **Given** um identificador inexistente, **When** o operador o acessa, **Then** vê "empresa não encontrada" com volta para a lista.

---

### User Story 3 - Operador muda o estado de uma empresa pelo painel (Priority: P2)

Na ficha, o operador suspende, retoma ou encerra uma empresa. O painel só oferece as ações permitidas pela tabela de transições do ciclo de vida, pede confirmação e, em suspensão e encerramento, um motivo opcional que vai para a auditoria.

**Why this priority**: Substitui `suspend`, `resume` e `close` por um clique, mas o operador já faz isso hoje pela linha de comando; a leitura (P1) vem antes.

**Independent Test**: Suspender uma empresa ativa pelo painel; conferir que o estado mudou, que há linha de auditoria com o operador e o motivo, e que `tenants status` mostra "suspenso".

**Acceptance Scenarios**:

1. **Given** uma empresa ativa, **When** o operador escolhe "Suspender" e confirma, **Then** o estado vira suspenso, a tela reflete a mudança e a auditoria registra operador, motivo e horário.
2. **Given** uma empresa suspensa, **When** o operador escolhe "Retomar", **Then** volta a ativa.
3. **Given** uma empresa encerrada, **When** o operador abre a ficha, **Then** nenhuma ação de mudança de estado é oferecida.
4. **Given** uma empresa em configuração, **When** o operador tenta ativá-la, **Then** o painel exige a prontidão aprovada e, se não estiver, mostra quais itens faltam, sem ativar.
5. **Given** duas pessoas alterando a mesma empresa ao mesmo tempo, **When** a segunda confirma, **Then** recebe a mensagem de transição inválida com o estado atual, e a tela se atualiza.
6. **Given** o operador fecha a janela de confirmação, **When** volta à ficha, **Then** nada mudou.

---

### User Story 4 - Operador cadastra e gerencia as empresas numa tela própria (Priority: P2)

Numa tela "Empresas" o operador vê todas as empresas numa lista de gestão (nome, `slug`, nicho, plano, estado, situação da conexão, documentos, data de criação) e, a partir dela, cadastra uma nova empresa ou edita uma existente em um formulário. O formulário reúne: identificação (nome, `slug`, nicho, plano), configuração do atendimento (tom de voz, horário de funcionamento, limite de desconto, confiança mínima para handoff, tópicos proibidos, palavras-gatilho, limite de mensagens por minuto, duração do handoff), conexão do canal (instância, segredo de entrega, chave de envio) e envio de documentos para a base de conhecimento.

**Why this priority**: O cadastro é raro (algumas empresas por mês) e a linha de comando já o cobre, mas é o fluxo mais sujeito a erro de digitação e o que mais depende de conhecer comandos e formato de arquivo. Vem logo depois de leitura (P1) e mudança de estado (P2).

**Independent Test**: Criar uma empresa pelo formulário com o mesmo conteúdo de `docs/exemplos/empresa-modelo.yml` e verificar que o resultado é idêntico ao do comando `tenants create` (mesmos campos, mesma auditoria, estado "em configuração").

**Acceptance Scenarios**:

1. **Given** a tela Empresas, **When** o operador a abre, **Then** vê todas as empresas com busca por nome ou `slug`, filtro por estado e, em cada linha, as ações Ver e Editar (Editar não aparece para empresa encerrada nem para o papel de leitura).
2. **Given** o botão "Nova empresa", **When** o operador preenche o formulário com dados válidos e confirma, **Then** a empresa nasce em configuração, aparece na lista e a tela abre a ficha dela.
3. **Given** o formulário de criação, **When** o operador digita o nome, **Then** o `slug` é sugerido a partir do nome e pode ser ajustado antes de salvar; depois de criada, o `slug` não muda.
4. **Given** um `slug` já existente, uma instância de canal já usada por outra empresa, um segredo de entrega com menos de 32 caracteres, um horário fora do formato ou um número fora da faixa, **When** o operador tenta salvar, **Then** vê o erro específico junto ao campo, o foco vai para o primeiro campo com erro e nada é criado ou alterado.
5. **Given** a edição de uma empresa, **When** o operador altera campos e salva, **Then** só os campos alterados vão para a auditoria, com o valor anterior e o novo e o operador autenticado; salvar sem alterações informa "nenhuma alteração".
6. **Given** uma empresa com conexão já cadastrada, **When** o operador abre a edição, **Then** vê que as credenciais estão configuradas, sem nunca ver os valores, e só as substitui por ação explícita ("Substituir credenciais"); substituir exige nova verificação da conexão.
7. **Given** o envio de documentos, **When** o operador escolhe arquivos, **Then** vê a lista com nome e tamanho, pode remover antes de salvar, e arquivos de formato ou tamanho inválido são recusados com mensagem; ao salvar, a ficha mostra a nova contagem de documentos e trechos.
8. **Given** o papel de leitura, **When** tenta abrir o formulário (inclusive por endereço direto), **Then** vê que não tem permissão e nada é salvo.
9. **Given** duas pessoas editando a mesma empresa, **When** a segunda salva depois da primeira, **Then** é avisada de que a empresa mudou e vê os valores atuais antes de decidir; uma não sobrescreve a outra sem perceber.

---

### User Story 5 - Operador acompanha conversas por metadados, sem dados pessoais (Priority: P3)

Na ficha da empresa, o operador vê a lista das conversas recentes (identificador curto, canal, status, agente atual, início, última atividade, quantidade de mensagens) e, quando necessário, abre uma conversa para entender um handoff ou um erro. A conversa mostra apenas metadados: linha do tempo de remetente, tipo e horário de cada mensagem, intenção detectada, confiança e motivo do handoff. O painel nunca mostra o texto das mensagens nem o contato (nem mascarado).

**Why this priority**: Útil para depurar sem tocar em dados pessoais de terceiros (constituição, princípio IV). Fica P3 porque a ficha (P1) já mostra os agregados.

**Independent Test**: Abrir uma conversa com texto e telefone conhecidos e conferir que nenhum dos dois aparece em tela, na resposta da API nem em log, e que os metadados batem com a base.

**Acceptance Scenarios**:

1. **Given** a lista de conversas, **When** exibida, **Then** cada linha mostra identificador curto, canal, status, agente atual, início, última atividade e total de mensagens, sem contato.
2. **Given** uma conversa em handoff, **When** o operador a abre, **Then** vê o motivo, a confiança no momento, a intenção detectada e a linha do tempo de remetente, tipo e horário.
3. **Given** qualquer conversa, **When** o operador tenta ver o texto, **Then** não existe ação para isso; o painel só oferece o identificador completo para ele localizar o caso por outros meios autorizados.

---

### Edge Cases

- **Empresa com milhares de mensagens/dia**: a visão geral continua abrindo em tempo aceitável (SC-002), usando agregações e não a leitura de mensagens uma a uma.
- **Fuso horário**: "hoje" e os dias das séries seguem o fuso de São Paulo, igual ao horário de funcionamento das empresas; o painel informa qual fuso usa.
- **Dados defasados**: os números podem estar até 5 minutos atrás da realidade; a tela mostra "atualizado há X" e o botão "Atualizar" força a releitura. Passou de 10 minutos sem atualização, o bloco mostra aviso de dados desatualizados.
- **Falha parcial**: se um bloco falhar (por exemplo, custo), os demais continuam visíveis e o bloco com falha mostra o erro e um botão de tentar de novo.
- **Empresa suspensa**: continua aparecendo com os dados históricos; mensagens recebidas durante a suspensão (`recebida_em_suspensao`) são contadas à parte.
- **Mensagens não textuais**: entram na contagem total e aparecem separadas ("áudio/imagem sem tratamento").
- **Sessão expirada no meio de uma ação de escrita**: a ação não é executada; o operador faz login de novo e a tela volta ao ponto onde estava.
- **Operador com permissão só de leitura** tentando uma ação de escrita: o botão nem aparece, e uma chamada direta é recusada.
- **Muitas empresas** (centenas): lista paginada, busca e filtros no servidor.
- **Tela pequena**: o painel é usável em tablet e as telas de leitura (P1, P2) funcionam no celular; formulários longos (P4) podem exigir tela maior.

## Requirements *(mandatory)*

### Functional Requirements

**Acesso e segurança**

- **FR-001**: O painel DEVE exigir identificação do operador antes de qualquer tela ou dado; sem sessão válida, nada é exibido.
- **FR-002**: O painel DEVE distinguir pelo menos dois papéis: **leitura** (vê tudo que não é dado pessoal) e **operação** (também muda estado e configuração). Ações de escrita DEVEM ser recusadas para o papel de leitura mesmo por chamada direta.
- **FR-003**: Toda mudança feita pelo painel DEVE ser registrada na mesma trilha de auditoria da linha de comando, com o operador autenticado (não um texto livre).
- **FR-004**: O painel NÃO DEVE exibir, em nenhuma tela, resposta de API, log ou erro: segredo de entrega, chave de envio, hash de credencial, nem telefone ou texto de contato sem mascaramento.
- **FR-005**: O painel NÃO DEVE oferecer nenhuma forma de ver o texto das mensagens nem o contato (telefone ou identificador do canal) de clientes finais; só metadados (remetente, tipo, horário, intenção, confiança, motivo do handoff).
- **FR-006**: Sessões DEVEM expirar por inatividade e o operador DEVE poder encerrá-las.
- **FR-007**: Ações destrutivas ou irreversíveis (encerrar, apagar dados) DEVEM exigir confirmação digitando o nome exato da empresa, como `purge --confirmar` já exige.

**Visão geral (dashboard agregado)**

- **FR-008**: A visão geral DEVE mostrar, para o período escolhido: total de empresas por estado; total de mensagens (recebidas, enviadas por agente, enviadas por humano); total de conversas por status; conversas aguardando humano agora; taxa de handoff; custo total e tokens.
- **FR-009**: A visão geral DEVE oferecer os períodos hoje, 7 dias e 30 dias, e a comparação com o período anterior de mesma duração (variação percentual).
- **FR-010**: A visão geral DEVE mostrar a evolução diária de mensagens e de custo no período, somando todas as empresas.
- **FR-011**: A visão geral DEVE listar as empresas que pedem atenção: ativas sem atividade acima do limite, com taxa de handoff acima do limite, com custo acima do orçamento, com conexão do canal não verificada, ou com falhas de envio.
- **FR-012**: Os limites de atenção DEVEM ser configuráveis sem alterar código, com valores iniciais globais de 24 horas sem mensagem (só empresas ativas), taxa de handoff acima de 30% das conversas do período e custo em 90% ou mais do orçamento mensal da empresa.
- **FR-043**: O orçamento mensal de custo de cada empresa DEVE ser derivado do plano dela, a partir de uma tabela plano → valor (em US$) mantida em configuração, e não de um campo por empresa. Plano sem valor na tabela aparece como "sem orçamento" e não dispara alerta de custo. A barra de orçamento da lista e da ficha usa esse valor.
- **FR-044**: A tabela de planos (FR-043) DEVE guardar também o preço mensal de cada plano em US$, usado só para a margem estimada: por empresa na ficha e total na visão geral. Plano sem preço mostra "margem indisponível", nunca zero. A tabela é alterada por configuração, e a alteração é auditada.

**Tabela e lista de empresas**

- **FR-013**: A lista DEVE mostrar por empresa: nome, `slug`, nicho, plano, estado, data de ativação, mensagens no período, conversas abertas, handoffs no período, data e hora da última mensagem (e quem enviou: contato, agente ou humano), custo no período e situação da conexão.
- **FR-014**: A lista DEVE permitir busca por nome ou `slug`, filtro por estado e nicho, ordenação por qualquer coluna numérica ou de data e paginação.
- **FR-015**: A lista DEVE permitir exportar a visão atual (com os filtros aplicados) em formato tabular, sem dados pessoais.

**Ficha da empresa**

- **FR-016**: A ficha DEVE mostrar todos os dados que `tenants status` mostra (identificação, estado e datas, documentos e trechos, conexão, última prontidão, último teste).
- **FR-017**: A ficha DEVE mostrar, para o período: mensagens por remetente e por tipo (texto, não texto); conversas por status e canal; taxa de handoff e principais motivos; tempo médio e percentil 95 de resposta; distribuição de intenções; mensagens bloqueadas por guardrail; taxa de falha de envio.
- **FR-018**: A ficha DEVE mostrar custo e tokens por dia, por finalidade e por modelo, custo por conversa e a margem estimada do período (preço mensal do plano proporcional ao período menos o custo de API).
- **FR-019**: A ficha DEVE mostrar a configuração atual da empresa e o histórico de auditoria, paginado, em ordem do mais recente.
- **FR-020**: A ficha DEVE mostrar a última mensagem de cada conversa recente apenas como metadados (remetente, tipo, horário), conforme FR-004 e FR-005.

**Ações**

- **FR-021**: O painel DEVE oferecer suspender, retomar e encerrar, respeitando exatamente a tabela de transições do ciclo de vida, e DEVE recusar com mensagem clara qualquer transição fora dela.
- **FR-022**: Ativar uma empresa DEVE exigir prontidão aprovada; o painel DEVE mostrar quais itens faltam quando reprovada.
- **FR-023**: O painel DEVE permitir disparar a verificação de prontidão e a conversa de teste e exibir o resultado.
- **FR-024**: (P2) O painel DEVE ter uma tela "Empresas" com a lista de gestão (nome, `slug`, nicho, plano, estado, situação da conexão, número de documentos, data de criação), busca, filtro por estado e acesso à ficha e à edição de cada empresa.
- **FR-034**: (P2) O painel DEVE permitir criar empresa por formulário com identificação, configuração do atendimento, conexão do canal e documentos, com as mesmas validações, a mesma idempotência e a mesma auditoria da linha de comando (`tenants create`, `config set`); a empresa nasce em configuração.
- **FR-035**: (P2) O painel DEVE validar cada campo antes de enviar e DEVE repetir a validação no servidor: `slug` único, só minúsculas, números e hífen, até 63 caracteres; instância do canal não usada por outra empresa; segredo de entrega com pelo menos 32 caracteres; chave de envio não vazia; horário no formato HH:MM-HH:MM ou "fechado"; números dentro das faixas permitidas. Erros aparecem junto ao campo, em português, sem revelar dados de outras empresas.
- **FR-036**: (P2) O `slug` DEVE ser sugerido a partir do nome na criação e NÃO DEVE poder ser alterado depois.
- **FR-037**: (P2) Na edição, o painel DEVE gravar na auditoria apenas os campos realmente alterados, com valor anterior, valor novo e operador; credenciais DEVEM aparecer só como marca ("••••"), nunca como valor.
- **FR-038**: (P2) As credenciais já cadastradas NUNCA DEVEM ser devolvidas ao navegador; o formulário mostra "configuradas" e só aceita novos valores por ação explícita, que passa a exigir nova verificação da conexão.
- **FR-039**: (P2) Empresa encerrada NÃO DEVE ser editável; empresa suspensa PODE ter configuração e documentos editados, sem mudar o estado.
- **FR-040**: (P2) Duas edições simultâneas da mesma empresa NÃO DEVEM se sobrescrever sem aviso: o painel DEVE detectar que a empresa mudou desde que o formulário foi aberto e mostrar o conflito.
- **FR-041**: (P2) O envio de documentos DEVE aceitar só formatos de texto suportados pelo ingestor (hoje `.md` e `.txt`) até um tamanho máximo por arquivo, recusar nomes repetidos na mesma remessa e mostrar o resultado do processamento (documentos e trechos criados) na ficha.
- **FR-025**: (P3) O apagamento de dados de empresa encerrada (`purge`) DEVE continuar disponível só com a confirmação por nome e permissão de operação; DEVE mostrar o resumo do que será apagado antes.

**Qualidade da informação**

- **FR-026**: Todo número exibido DEVE ter definição consultável (dica na tela) de como é calculado e a qual período se refere.
- **FR-027**: Todo bloco DEVE mostrar quando foi atualizado pela última vez e ter estados de carregamento, vazio e erro.
- **FR-042**: Os números do painel DEVEM refletir a realidade com atraso máximo de 5 minutos, e o operador DEVE poder forçar a atualização a qualquer momento.
- **FR-028**: Os números do painel DEVEM coincidir com os da linha de comando e da base para o mesmo período; divergência é defeito.

**Identidade visual**

- **FR-031**: O painel DEVE seguir o design system do projeto (`design-system/`): tema escuro, acento teal, tipografia e componentes (cartões, pílulas de período, badges de estado, tabela, donut, linhas e barras em gráficos simples) iguais aos do protótipo de referência `design-system/plantao-admin.html`, sem criar um segundo estilo visual.
- **FR-032**: A cor nunca DEVE ser o único sinal de estado ou de alerta: todo badge, alerta e variação traz também texto ou ícone, e o contraste do texto sobre o fundo escuro atende ao nível AA.
- **FR-033**: A navegação DEVE ser vertical, numa barra lateral recolhível (com rótulo ao passar o mouse quando recolhida); em tela estreita vira menu sobreposto.

**Isolamento e privacidade**

- **FR-029**: O painel DEVE ler dados de empresas pelos mesmos mecanismos de isolamento do restante do sistema; nenhuma tela ou chamada DEVE misturar dados de duas empresas fora das agregações propositais da visão geral, e estas DEVEM conter só contagens e somas.
- **FR-030**: O painel DEVE respeitar a exclusão de dados: após o `purge`, dados pessoais nunca reaparecem em tela, exportação ou cache.

### Key Entities *(include if feature involves data)*

- **Operador**: pessoa autenticada que usa o painel. Tem identidade, papel (leitura ou operação) e sessão. Seu identificador é o que vai para a auditoria.
- **Empresa (tenant)**: já existente; o painel passa a criá-la e editá-la (identificação, configuração, conexão, documentos). O painel a mostra com nome, `slug`, nicho, plano, estado e datas do ciclo de vida.
- **Resumo de atividade da empresa**: valores derivados por empresa e período: mensagens por remetente e tipo, conversas por status, handoffs, última mensagem (horário e remetente), tempo de resposta, custo, tokens. Não é cadastro; é leitura calculada, podendo ser pré-agregada.
- **Alerta de atenção**: condição calculada que sinaliza uma empresa (sem atividade, handoff alto, custo alto, conexão sem verificar, falhas de envio), com o limite que a disparou.
- **Limites de atenção**: parâmetros que definem os alertas (FR-012).
- **Tabela de planos**: configuração que associa cada plano a um orçamento mensal de custo e a um preço mensal (ambos em US$); alimenta o alerta de custo e a margem estimada.
- **Conexão do canal, Documento de conhecimento, Prontidão, Auditoria**: já existentes; o painel os exibe e, no P3, os altera.

## Clarificações pendentes

Marcadores `[NEEDS CLARIFICATION]` para resolver antes do plano (`/speckit-clarify`):

1. **Quem é o operador e como se autentica?** Hoje o "operador" é um texto livre (`--operador`) e não existe login. Opções: (a) usuário e senha próprios com papéis; (b) login por provedor externo (Google); (c) acesso protegido por rede/VPN com um único perfil. A escolha define FR-001, FR-002 e a confiabilidade da auditoria. **Resolvida:** opção (b), com dois papéis (leitura e operação), conforme [ADR-0007](../../docs/adr/0007-autenticacao-do-operador.md).
2. ~~O painel pode mostrar conteúdo de mensagem?~~ **Resolvida** em 2026-10-06 (ver Clarifications): só metadados.
3. ~~Visão de cliente (dono da empresa)~~ **Resolvida**: fora do escopo desta spec (ver Premissas); terá outra spec e outro modelo de acesso.
4. ~~Valores dos limites de atenção~~ **Resolvida** em 2026-10-06 (ver Clarifications): 24 h, 30% e 90%.
5. ~~Margem estimada~~ **Resolvida** em 2026-10-06 (ver Clarifications): preço por plano, em tabela de configuração.
6. ~~Frescor dos números~~ **Resolvida** em 2026-10-06 (ver Clarifications): até 5 minutos.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: O operador responde "como está cada empresa?" (estado, volume e última mensagem de todas) em menos de 30 segundos, sem usar a linha de comando, medido com 3 operadores.
- **SC-002**: A visão geral abre em até 3 segundos com 50 empresas e 1 milhão de mensagens no histórico; a ficha de uma empresa, em até 3 segundos com 100 mil mensagens.
- **SC-003**: 100 % dos números da visão geral e da ficha coincidem com a contagem direta na base para o mesmo período, verificado em teste automatizado sobre dados de duas empresas.
- **SC-004**: Zero ocorrências de segredo, hash de credencial, telefone ou texto de mensagem sem mascaramento em tela, resposta de API, log ou exportação, verificado por teste automatizado e revisão.
- **SC-005**: 100 % das mudanças feitas pelo painel aparecem na auditoria com o operador autenticado; nenhuma mudança de estado fora da tabela de transições é aceita.
- **SC-006**: Suspender uma empresa e confirmar leva menos de 15 segundos a partir da lista e passa a valer para novas mensagens imediatamente.
- **SC-007**: Um operador identifica qual empresa tem problema de atendimento (sem atividade, handoff alto ou custo alto) em menos de 10 segundos a partir da abertura do painel, em 9 de 10 tentativas.
- **SC-008**: Os fluxos de leitura (P1 e P2) são utilizáveis em celular, sem rolagem horizontal da página.
- **SC-009**: Um operador cadastra uma empresa completa (identificação, configuração, conexão e documentos) pelo formulário em menos de 5 minutos, sem consultar o runbook, e o resultado é idêntico ao de `tenants create` com o mesmo conteúdo.
- **SC-010**: 100 % dos erros de validação de cadastro (`slug` repetido, instância em uso, segredo curto, formato inválido) aparecem junto ao campo, antes de qualquer gravação, e nenhuma credencial aparece em tela, resposta ou log.

## Assumptions

- Usuários do painel são poucos (1 a 5 operadores da plataforma); não é produto para o cliente final.
- O painel é feito em português do Brasil; datas e horas em fuso de São Paulo e moeda de custo em dólar (como já registrado em `llm_calls`), com conversão para real fora do escopo desta versão.
- Os dados necessários já existem na base (mensagens, conversas, handoffs, chamadas de LLM, métricas de uso, conexões, prontidão, auditoria); a primeira versão não exige coletar dado novo, apenas expor e agregar. Pode haver necessidade de agregações pré-calculadas, a decidir no plano.
- As regras de ciclo de vida, de isolamento entre empresas e de exclusão de dados (specs 001 e 002) não mudam; o painel as obedece.
- O painel só lê e escreve através da API do sistema. Hoje a API não tem rotas de operação: elas serão criadas por esta feature, e o acesso administrativo entre empresas hoje restrito a `scripts/` (`db/admin.py`: "nenhum módulo de `apps/` pode importar este") exige decisão no plano sobre como a API fará leituras entre empresas sem enfraquecer o isolamento (provável ADR).
- O protótipo `design-system/plantao-admin.html` usa dados fictícios e serve só de referência visual (estrutura, componentes e textos); não é código de produção nem define o contrato da API.
- Fora do escopo: visão de cliente (dono da empresa), cobrança e faturamento, edição de conversas, resposta manual de handoff pelo painel, notificações push ou por e-mail dos alertas, integração com ferramentas de BI, internacionalização e tema personalizável.
- Fica para o plano: escolha de tecnologias de front-end, desenho da API, estratégia de agregação, autenticação concreta e hospedagem. O front-end fica em `apps/dashboard/` (já previsto na estrutura, sem diretório de topo novo); decisões propostas em [ADR-0005](../../docs/adr/0005-front-end-do-painel.md), [ADR-0006](../../docs/adr/0006-leitura-entre-empresas-pela-api.md) e [ADR-0007](../../docs/adr/0007-autenticacao-do-operador.md).
