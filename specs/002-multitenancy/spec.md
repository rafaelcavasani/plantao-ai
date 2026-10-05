# Feature Specification: Multi-tenancy real

**Feature Branch**: `002-multitenancy`

**Created**: 2026-10-04

**Status**: Draft

**Input**: User description: "Sprint 3 — Multi-tenancy" (Projeto_Empresa_Autonoma.md, seção 8.7: "Sprint 3 — Multi-tenancy real: modelo de dados completo, onboarding programático de um novo tenant, isolamento testado"; seção 8.9, checklist de segurança; seção 8.10, critério "pronto para vender")

Esta é a primeira de duas especificações do Sprint 3. A segunda, [003-landing-page](../003-landing-page/spec.md), é independente desta e pode ser planejada, entregue e validada em separado.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Cada mensagem é atendida pela empresa certa (Priority: P1)

Duas ou mais empresas clientes (por exemplo, a clínica piloto e um segundo cliente) estão ativas ao mesmo tempo, cada uma com o seu número de WhatsApp. Quando um cliente final escreve para o número de uma empresa, o sistema identifica qual é a empresa, responde com o tom de voz, o horário, as regras de segurança e os documentos daquela empresa e envia a resposta pelo número dela.

**Why this priority**: É o que transforma o sistema de "uma empresa fixa" em plataforma. Sem isso não há segundo cliente e o cliente beta não pode entrar.

**Independent Test**: Ativar duas empresas com horários, preços e tópicos proibidos diferentes. Enviar a mesma pergunta ("Qual o horário de sábado?") para o número de cada uma. Cada uma deve receber a resposta baseada nos seus próprios documentos, enviada pelo seu próprio número.

**Acceptance Scenarios**:

1. **Given** as empresas A e B ativas com documentos diferentes, **When** um cliente pergunta o preço de um serviço ao número de A, **Then** a resposta traz o valor do documento de A e nenhuma informação de B.
2. **Given** a empresa A com limite de desconto de 10% e a empresa B com 0%, **When** o agente gera uma resposta com desconto de 5% para cada uma, **Then** a resposta de A é enviada e a de B é repassada a um humano.
3. **Given** uma mensagem recebida por um número que não pertence a nenhuma empresa, **When** o sistema a recebe, **Then** nada é respondido, nenhum dado pessoal é guardado e o evento é registrado sem identificar o cliente.
4. **Given** uma entrega de mensagem autenticada com a credencial da empresa A, **When** ela tenta registrar uma mensagem como se fosse da empresa B, **Then** a entrega é recusada.
5. **Given** a empresa piloto já em uso antes desta entrega, **When** o sistema passa a operar com várias empresas, **Then** as conversas, os documentos e a configuração da empresa piloto continuam disponíveis e funcionando sem recadastro.

---

### User Story 2 - Operador cria uma nova empresa por procedimento repetível (Priority: P1)

O operador da agência cadastra uma nova empresa cliente por um procedimento programático (um comando alimentado por um arquivo de configuração), sem alterar código. O procedimento cria a empresa, aplica a configuração, conecta o número de WhatsApp, carrega os documentos e roda uma verificação de prontidão. A empresa só começa a atender clientes finais depois que o operador a ativa de forma explícita.

**Why this priority**: É o critério de saída do MVP (seção 8.10): "um novo tenant pode ser configurado em menos de 2 horas de trabalho manual". Sem procedimento repetível, cada cliente novo vira projeto sob medida.

**Independent Test**: Partindo de um arquivo de configuração e de uma pasta de documentos, criar uma empresa nova do zero, rodar a verificação de prontidão, simular uma conversa de teste, ativar a empresa e receber uma resposta correta de um número real de teste. Medir o tempo de trabalho manual.

**Acceptance Scenarios**:

1. **Given** um arquivo de configuração válido e uma pasta de documentos, **When** o operador executa o procedimento de criação, **Then** a empresa é criada no estado "em configuração" com a configuração aplicada, o número conectado e os documentos indexados, e o operador vê um resumo do que foi feito.
2. **Given** uma empresa em configuração, **When** o operador pede a verificação de prontidão, **Then** o sistema informa, item a item, se a configuração está completa, se há ao menos um documento indexado, se o número está conectado e verificado, e se uma conversa simulada de teste foi executada.
3. **Given** a verificação de prontidão com algum item pendente, **When** o operador tenta ativar a empresa, **Then** a ativação é recusada e o sistema lista o que falta.
4. **Given** uma empresa em configuração, **When** o operador a ativa depois de a verificação passar, **Then** a empresa passa a responder clientes finais e a ativação fica registrada com data e responsável.
5. **Given** o procedimento de criação interrompido no meio (falha de rede, documento inválido), **When** o operador o executa de novo com o mesmo arquivo, **Then** o procedimento continua de onde parou, sem duplicar a empresa, o número ou os documentos, e nenhuma empresa incompleta fica ativa.
6. **Given** um arquivo de configuração com valores inválidos (confiança fora de 0 a 1, limite de desconto acima de 100%), **When** o operador executa o procedimento, **Then** nada é criado e a mensagem de erro indica cada campo inválido.

---

### User Story 3 - Isolamento entre empresas é comprovado por testes (Priority: P1)

O responsável pelo produto precisa de prova automatizada de que os dados de uma empresa nunca aparecem para outra: conversas, mensagens, documentos, buscas de conhecimento, registros de uso, repasses humanos, fila de processamento, contadores de limite, credenciais e logs. A prova roda em toda alteração do código.

**Why this priority**: Um vazamento entre clientes é o pior incidente possível para o negócio e para a LGPD (constituição, princípio III). Este é o item "isolamento testado" do Sprint 3.

**Independent Test**: Criar três empresas com dados distintos e executar a suíte de isolamento. Todos os cenários devem passar, e uma alteração que quebre o isolamento de propósito deve fazer a suíte falhar.

**Acceptance Scenarios**:

1. **Given** as empresas A e B com conversas e documentos, **When** uma consulta é feita no contexto de A, **Then** ela não devolve nenhuma linha de B, em nenhuma entidade.
2. **Given** a mesma pessoa (mesmo telefone) escrevendo para A e para B, **When** ambas as conversas são processadas, **Then** há duas conversas independentes, sem histórico compartilhado, e a resposta de uma nunca usa o histórico da outra.
3. **Given** o mesmo identificador de mensagem recebido por A e por B, **When** ambas são processadas, **Then** cada uma é processada e respondida uma única vez, sem colisão.
4. **Given** uma empresa que excede o seu limite de mensagens por minuto, **When** B recebe mensagens ao mesmo tempo, **Then** B não é afetada pelo contador de A.
5. **Given** uma falha no número de A (credencial inválida ou revogada), **When** B envia e recebe mensagens, **Then** B continua operando normalmente e a falha de A é registrada.
6. **Given** a ausência de empresa definida no contexto da consulta, **When** qualquer dado de negócio é consultado, **Then** nenhuma linha é devolvida.

---

### User Story 4 - Operador suspende e reativa uma empresa em caso de incidente (Priority: P2)

Se um agente errar em uma empresa (promessa indevida, resposta ofensiva), o operador precisa pausar essa empresa rapidamente, sem derrubar as demais, e reativá-la quando o problema estiver resolvido.

**Why this priority**: Faz parte do critério de saída do MVP (seção 8.10, "processo documentado de rollback/pausa rápida de um tenant em caso de incidente"). Não é necessário para atender o primeiro cliente, mas é necessário antes de cobrar.

**Independent Test**: Com A e B ativas e mensagens aguardando processamento, suspender A. Verificar que A deixa de enviar respostas automáticas, que B segue normal e que, ao reativar A, o atendimento volta.

**Acceptance Scenarios**:

1. **Given** a empresa A ativa, **When** o operador a suspende, **Then** em até 1 minuto nenhuma nova resposta automática sai pelo número de A, inclusive para mensagens que já estavam aguardando processamento.
2. **Given** a empresa A suspensa, **When** um cliente final escreve para A, **Then** a mensagem é guardada para o histórico, nenhuma resposta automática é enviada e a conversa fica identificável como recebida durante a suspensão.
3. **Given** a empresa A suspensa, **When** o operador a reativa, **Then** as novas mensagens voltam a ser respondidas e o histórico é preservado.
4. **Given** qualquer mudança de estado de uma empresa, **When** ela ocorre, **Then** fica registrado quem a fez, quando e qual era o estado anterior.

---

### User Story 5 - Operador ajusta a configuração de uma empresa sem afetar as outras (Priority: P2)

O operador altera regras de uma empresa (tom de voz, horário, tópicos proibidos, limite de desconto, confiança mínima, palavras-gatilho, limite de mensagens por minuto, tempo de espera do repasse humano) sem reiniciar o sistema e sem tocar nas outras empresas. Cada alteração fica registrada.

**Why this priority**: Depois do primeiro cliente real, os ajustes de guardrails são frequentes (seção 7.7). A trilha de auditoria é exigência da constituição (princípio IV).

**Independent Test**: Alterar o limite de desconto da empresa A. Verificar que a próxima mensagem de A já usa o novo limite, que B continua com o dela e que existe um registro com valor anterior, valor novo, autor e data.

**Acceptance Scenarios**:

1. **Given** a empresa A ativa, **When** o operador altera uma regra, **Then** a próxima mensagem de A já usa o novo valor, sem reinício do sistema.
2. **Given** uma alteração de configuração, **When** ela é salva, **Then** o registro de auditoria guarda o campo, o valor anterior, o valor novo, o autor e a data.
3. **Given** um valor inválido, **When** o operador tenta salvá-lo, **Then** a alteração é recusada e o valor anterior permanece.
4. **Given** uma conversa em andamento, **When** a configuração muda, **Then** a mudança vale a partir da próxima mensagem, sem reprocessar mensagens já respondidas.

---

### User Story 6 - Operador encerra uma empresa e apaga os dados dela (Priority: P3)

Quando um cliente cancela o contrato ou pede a exclusão dos dados, o operador encerra a empresa e, mediante confirmação explícita, apaga todos os dados dela sem tocar nos das outras.

**Why this priority**: A LGPD exige exclusão sob demanda (constituição, princípio IV), mas nenhum cliente cancela antes de existirem clientes. Entra na entrega para que o ciclo de vida fique completo e porque é mais uma prova de isolamento.

**Independent Test**: Criar a empresa C com conversas, documentos e uso. Encerrá-la e apagá-la. Verificar que nada de C resta e que A e B estão idênticas ao estado anterior.

**Acceptance Scenarios**:

1. **Given** a empresa C ativa, **When** o operador a encerra, **Then** C deixa de responder clientes finais e o número dela é liberado para outro uso somente depois da exclusão dos dados.
2. **Given** a empresa C encerrada, **When** o operador pede a exclusão dos dados e confirma digitando o nome da empresa, **Then** conversas, mensagens, documentos, trechos de conhecimento, registros de uso, repasses, configuração e credenciais de C são apagados.
3. **Given** a exclusão de C concluída, **When** os dados de A e B são comparados com o estado anterior, **Then** nada mudou.
4. **Given** a exclusão de C concluída, **When** o operador consulta a trilha de auditoria, **Then** existe um registro de que a exclusão ocorreu (quem, quando, empresa), sem nenhum dado pessoal de clientes finais.
5. **Given** o pedido de exclusão sem a confirmação correta, **When** o operador o executa, **Then** nada é apagado.

---

### Edge Cases

- Mensagem para um número desconhecido, ou de empresa em configuração ou encerrada: não é processada, não grava dado pessoal e gera registro sem identificar o cliente. Empresa suspensa é outro caso: a mensagem é guardada, sem resposta (FR-017).
- Mensagens já na fila quando a empresa é suspensa ou encerrada: não geram resposta.
- Duas empresas tentando usar o mesmo número de WhatsApp: o segundo cadastro é recusado com mensagem clara.
- Mesmo cliente final escrevendo para duas empresas: duas conversas sem relação entre si.
- Mesmo identificador de mensagem em duas empresas: sem colisão, cada uma processada uma vez.
- Credencial de uma empresa inválida ou revogada: o envio falha apenas para ela, o fato é registrado e a conversa é repassada a um humano; as outras empresas seguem normais.
- Empresa que excede o limite de mensagens: apenas ela é limitada; as demais não ficam mais lentas.
- Criação interrompida no meio ou executada duas vezes com o mesmo arquivo: não duplica empresa, número ou documentos e nunca deixa uma empresa incompleta ativa.
- Empresa sem nenhum documento indexado: não pode ser ativada.
- Empresa nova sem configuração personalizada: recebe valores padrão seguros e, ao editá-los, não altera os valores padrão nem os de outras empresas.
- Ferramenta do operador (carregar documento, rodar teste) usada quando há mais de uma empresa: exige a escolha explícita da empresa, para que nada seja gravado na empresa errada por omissão.
- Alteração de configuração no meio de uma conversa: vale a partir da próxima mensagem.
- Exclusão de dados de uma empresa com mensagens ainda em processamento: o processamento é interrompido antes da exclusão e nenhuma resposta é enviada.
- Empresa piloto existente antes da entrega: segue funcionando após a mudança, com seus dados preservados.

## Requirements *(mandatory)*

### Functional Requirements

**Identificação e canal**

- **FR-001**: O sistema DEVE identificar a empresa destinatária de cada mensagem recebida pelo número de WhatsApp (conexão de canal) que a recebeu, sem depender de uma empresa fixa.
- **FR-002**: Cada conexão de canal DEVE pertencer a exatamente uma empresa. O sistema DEVE recusar o cadastro de uma conexão que já esteja em uso por outra empresa.
- **FR-003**: O sistema DEVE autenticar cada entrega de mensagem com a credencial da conexão de canal da empresa. Uma entrega autenticada com a credencial de uma empresa NÃO DEVE poder gravar mensagens em outra.
- **FR-004**: O sistema DEVE enviar cada resposta pela conexão da empresa dona da conversa, usando a credencial dessa empresa.
- **FR-005**: As credenciais de cada empresa DEVEM ficar protegidas em repouso e NÃO DEVEM aparecer em registros técnicos, mensagens de erro, saídas de comandos ou na trilha de auditoria.
- **FR-006**: Mensagens recebidas por uma conexão desconhecida, ou de empresa em configuração ou encerrada, NÃO DEVEM ser respondidas nem gravar dados pessoais. O sistema DEVE registrar o evento sem identificar o cliente final. O caso de empresa suspensa segue o FR-017.

**Configuração por empresa**

- **FR-007**: Cada empresa DEVE ter a sua própria configuração: tom de voz, horário de funcionamento, tópicos proibidos, limite de desconto, confiança mínima para responder, palavras-gatilho, limiares de roteamento e de similaridade, tempo de espera do repasse humano e limite de mensagens por minuto.
- **FR-008**: Toda empresa nova DEVE receber valores padrão seguros, definidos em um modelo único. Editar a configuração de uma empresa NÃO DEVE alterar o modelo nem as outras empresas.
- **FR-009**: O sistema DEVE validar os valores da configuração antes de salvá-los (por exemplo, confiança entre 0 e 1, limite de desconto entre 0% e 100%) e DEVE recusar valores inválidos informando cada campo.
- **FR-010**: Uma alteração de configuração DEVE valer a partir da próxima mensagem da empresa, sem reiniciar o sistema.

**Ciclo de vida**

- **FR-011**: Toda empresa DEVE estar em um destes estados: em configuração, ativa, suspensa ou encerrada. Somente empresas ativas recebem respostas automáticas.
- **FR-012**: O sistema DEVE oferecer um procedimento programático de criação de empresa, alimentado por um arquivo de configuração, que cria a empresa, aplica a configuração, conecta o número e indexa os documentos fornecidos, sem alteração de código.
- **FR-013**: O procedimento de criação DEVE ser repetível: executado de novo com o mesmo arquivo após uma interrupção, DEVE concluir o que faltava sem duplicar a empresa, a conexão ou os documentos.
- **FR-014**: O sistema DEVE oferecer uma verificação de prontidão que informe, para uma empresa em configuração: configuração completa e válida, ao menos um documento indexado, conexão de canal verificada e uma conversa simulada de teste executada.
- **FR-015**: A ativação de uma empresa DEVE exigir a verificação de prontidão aprovada e uma ação explícita do operador.
- **FR-016**: O operador DEVE poder suspender uma empresa. A suspensão DEVE interromper as respostas automáticas em até 1 minuto, inclusive para mensagens que já aguardam processamento, e NÃO DEVE afetar as outras empresas.
- **FR-017**: Durante a suspensão, o sistema DEVE continuar guardando as mensagens recebidas, sem responder, e DEVE sinalizar que a conversa foi recebida durante a suspensão.
- **FR-018**: O operador DEVE poder reativar uma empresa suspensa, preservando o histórico.
- **FR-019**: O operador DEVE poder encerrar uma empresa. A exclusão dos dados DEVE exigir confirmação explícita com o nome da empresa e DEVE apagar conversas, mensagens, documentos, trechos de conhecimento, registros de uso, repasses humanos, configuração e credenciais da empresa, sem alterar nenhum dado de outras empresas.
- **FR-020**: Uma conexão de canal só DEVE ser liberada para outra empresa depois da exclusão dos dados da empresa que a usava.

**Ferramentas do operador**

- **FR-021**: As ferramentas do operador para documentos de conhecimento (carregar, listar, remover) e para avaliação de qualidade DEVEM atuar sobre uma empresa nomeada explicitamente. Quando houver mais de uma empresa, NÃO DEVE existir empresa padrão implícita.

**Isolamento e proteção de dados**

- **FR-022**: Toda leitura e gravação de dados de negócio DEVE estar restrita à empresa do contexto. Na ausência de empresa no contexto, nenhum dado de negócio DEVE ser devolvido.
- **FR-023**: A busca de conhecimento, o histórico de conversa, os registros de uso, os repasses humanos, a fila de processamento, os contadores de limite de mensagens e os registros técnicos DEVEM ser separados por empresa.
- **FR-024**: O mesmo cliente final (mesmo telefone) que escreve para duas empresas DEVE ter conversas independentes, sem histórico compartilhado.
- **FR-025**: O mesmo identificador de mensagem recebido por duas empresas diferentes NÃO DEVE gerar colisão: cada empresa o processa uma vez.
- **FR-026**: O limite de mensagens por minuto DEVE ser aplicado por empresa. Uma empresa que o excede NÃO DEVE atrasar as demais.
- **FR-027**: A falha de uma conexão de canal (credencial inválida, serviço indisponível) DEVE ficar restrita à empresa afetada, ser registrada e levar a conversa a repasse humano.
- **FR-028**: O sistema DEVE manter automatizados os testes de isolamento com ao menos três empresas, executados em toda alteração do código. Cada entidade com dado de empresa DEVE ter ao menos um cenário.

**Auditoria e consentimento**

- **FR-029**: O sistema DEVE registrar, para cada mudança de configuração, de estado ou de conexão de canal de uma empresa: quem fez, quando, o valor anterior e o novo. Os valores de credenciais NÃO DEVEM ser registrados.
- **FR-030**: O sistema DEVE registrar, em cada conversa, quem iniciou o contato e quando, como base para a resposta automática (conversa iniciada pelo cliente final).
- **FR-031**: O sistema DEVE manter o registro de uso, de custo e de repasses humanos associado à empresa, como já exigido na entrega anterior, também para as novas empresas.

**Continuidade**

- **FR-032**: A empresa piloto existente DEVE continuar operando após a mudança, com conversas, documentos e configuração preservados e com a conexão de canal registrada no novo modelo.
- **FR-033**: As regras de comportamento dos agentes definidas na entrega anterior (guardrails, repasse humano, fundamentação em documentos, tratamento de entrada como dado) DEVEM valer para todas as empresas.

### Key Entities

- **Empresa (tenant)**: cliente da agência. Tem nome, nicho, plano, estado do ciclo de vida (em configuração, ativa, suspensa, encerrada) e datas de criação, ativação e encerramento. Dona de todos os dados de negócio.
- **Configuração da empresa**: regras de comportamento da empresa (tom de voz, horário, tópicos proibidos, limite de desconto, confiança mínima, palavras-gatilho, limiares, tempo de espera do repasse, limite de mensagens por minuto). Parte de um modelo padrão e é editável.
- **Conexão de canal**: ligação entre uma empresa e um número de WhatsApp. Guarda a identificação do número, o segredo de autenticação das entregas e a credencial de envio, ambos protegidos. Pertence a uma só empresa.
- **Verificação de prontidão**: resultado, item a item, da checagem que precede a ativação (configuração, documentos, conexão, conversa de teste), com data e responsável.
- **Registro de auditoria**: quem alterou o quê, quando, valor anterior e novo, para configuração, estado e conexão de canal. Também registra a exclusão de dados, sem dados pessoais de clientes finais.
- **Origem do contato**: em cada conversa, quem a iniciou e quando. Base para as respostas automáticas.
- **Documento e trecho de conhecimento, Conversa, Mensagem, Repasse humano, Registro de uso**: já existem desde a entrega anterior. Passam a ser sempre associados a uma empresa e isolados entre elas.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: O operador cria e ativa uma empresa nova, do zero até responder um cliente final de teste, em até 2 horas de trabalho manual, em 2 criações consecutivas.
- **SC-002**: Com três empresas ativas ao mesmo tempo, 100% das mensagens de um conjunto de teste de 30 por empresa recebem resposta baseada apenas nos documentos, na configuração e no número da própria empresa, e 0% contêm informação de outra.
- **SC-003**: 100% dos cenários da suíte de isolamento passam com três empresas, cobrindo conversas, mensagens, documentos, busca de conhecimento, uso, repasses, fila, contadores de limite, credenciais e exclusão. Uma quebra proposital do isolamento faz a suíte falhar.
- **SC-004**: Após a suspensão de uma empresa, nenhuma nova resposta automática sai por ela em até 1 minuto, e as demais mantêm a meta de resposta em até 10 segundos para pelo menos 90% das mensagens.
- **SC-005**: Uma alteração de configuração vale para a próxima mensagem em até 1 minuto, sem reinício do sistema, e 100% das alterações têm registro de auditoria completo.
- **SC-006**: Enquanto uma empresa excede o limite de mensagens, pelo menos 90% das mensagens das demais continuam sendo respondidas em até 10 segundos.
- **SC-007**: Depois da mudança, 100% dos dados da empresa piloto (conversas, documentos, configuração) permanecem disponíveis e as metas SC-001 a SC-010 da entrega anterior ([001-router-support-agent](../001-router-support-agent/spec.md)) continuam atendidas para cada empresa ativa.
- **SC-008**: A exclusão de dados de uma empresa remove 100% das linhas dela em todas as entidades e altera 0 linhas de outras empresas.
- **SC-009**: A tentativa de gravar uma mensagem de uma empresa com a credencial de outra é recusada em 100% dos casos testados.
- **SC-010**: Em 100% das tentativas, a ativação de uma empresa com verificação de prontidão incompleta é recusada.

## Assumptions

- A empresa piloto (clínica) continua sendo a primeira empresa ativa. A segunda e a terceira empresas usadas nos testes são fictícias ou do cliente beta. A criação de uma empresa real, com número real, valida o critério de 2 horas.
- Cada empresa usa o seu próprio número de WhatsApp, atendido pela mesma plataforma (conexão de canal própria por empresa, conforme a seção 8.9 do documento do projeto). Um número compartilhado entre empresas fica fora desta entrega.
- O procedimento programático de criação é operado por linha de comando e por arquivo de configuração. Não há interface web de autoatendimento para o cliente nesta entrega.
- O operador e o desenvolvedor são a mesma pessoa. Quem "faz" uma ação na trilha de auditoria é identificado pelo nome do operador informado no comando.
- Durante a suspensão, a empresa suspensa não responde clientes finais. Essa escolha é a mais segura em caso de incidente. Um aviso automático de indisponibilidade pode ser avaliado depois.
- Na etapa atual os agentes só respondem a mensagens iniciadas pelo cliente final, que é a base de contato registrada. Mensagens proativas, descadastro e lembretes são tratados no Sprint 4.
- Todas as empresas usam uma chave única de proteção de dados pessoais da plataforma. Chaves separadas por empresa ficam fora desta entrega.
- Os limites de mensagens por minuto e os demais valores padrão têm valores iniciais razoáveis definidos no planejamento e ajustáveis por empresa.
- Fora de escopo desta entrega: agentes de agendamento, SDR e cobrança (Sprints 4 e 5); painel de custos, observabilidade avançada e cobrança recorrente dos clientes (Sprint 6); fila e painel de atendentes humanos (Sprint 5); outros canais além do WhatsApp; chaves de criptografia por empresa; interface web de onboarding.
- A landing page da Plantão.AI é tratada em [003-landing-page](../003-landing-page/spec.md) e não depende desta entrega.
- Segue a constituição do projeto (`.specify/memory/constitution.md`), em especial os princípios III (multi-tenancy), IV (privacidade e LGPD), V (guardrails), VI (spec primeiro) e VII (observabilidade e custo).
