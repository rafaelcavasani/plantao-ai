# Feature Specification: Landing page no ar

**Feature Branch**: `003-landing-page`

**Created**: 2026-10-04

**Status**: Draft

**Input**: User description: "Sprint 3 — Landing page no ar" (Projeto_Empresa_Autonoma.md: seção 9.5 "Criar landing page one-page: proposta de valor, catálogo de produtos (seção 7.4), prova social, CTA para WhatsApp/agendamento de demo"; seção 9.6, semana 5, coluna Marca/Legal "Landing page no ar")

Esta é a segunda de duas especificações do Sprint 3. A primeira, [002-multitenancy](../002-multitenancy/spec.md), é independente desta e pode ser planejada, entregue e validada em separado. A landing page não depende de nenhuma mudança no sistema de atendimento.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dono de PME entende a proposta e inicia uma conversa (Priority: P1)

Um dono de pequena empresa (clínica, academia, imobiliária) chega à página por indicação, rede social ou busca. Em poucos segundos entende o que a Plantão.AI faz por ele, vê quais "funcionários digitais" existem e toca no botão para conversar pelo WhatsApp com a empresa.

**Why this priority**: É o ativo comercial central da semana 5: sem página no ar, a prospecção depende só de conversa individual. "Landing page no ar" é o nome do marco.

**Independent Test**: Mostrar a página a 5 donos de pequenas empresas por 15 segundos. Pelo menos 4 devem explicar com as próprias palavras o que o serviço faz e apontar como entrar em contato. Em seguida, tocar no botão e verificar que o WhatsApp da empresa abre com a mensagem inicial preenchida.

**Acceptance Scenarios**:

1. **Given** um visitante no celular, **When** abre a página, **Then** vê, sem rolar, a proposta de valor em termos de resultado para o negócio (não de tecnologia), o nome e o lema da marca e o botão principal de contato.
2. **Given** o visitante rolando a página, **When** chega à seção de produtos, **Then** vê o Recepcionista, o Agendador, o SDR, o Cobrador, o Pós-venda e o pacote completo, cada um com a função em uma frase, e identifica quais estão disponíveis hoje e quais estão "em breve".
3. **Given** o visitante tocando no botão de contato, **When** está no celular, **Then** abre uma conversa de WhatsApp com a empresa e uma mensagem inicial já preenchida que identifica a origem (a página).
4. **Given** o visitante em um computador sem o aplicativo, **When** clica no botão, **Then** abre o WhatsApp na web ou, se isso não for possível, vê o número para copiar.
5. **Given** o visitante lendo a seção "Como funciona", **When** termina de lê-la, **Then** entende, em três passos, como o serviço é conectado, como aprende os documentos da empresa e quando passa a conversa para uma pessoa.

---

### User Story 2 - Visitante confia na empresa antes de escrever (Priority: P2)

O visitante quer saber quem está por trás do serviço, o que acontece com os dados dos clientes dele e se há prova de que funciona. A página mostra a identidade da empresa, as políticas legais e, enquanto não houver cliente autorizado a aparecer, um convite ao programa beta no lugar de depoimentos.

**Why this priority**: PMEs compram de quem confiam (seção 7.7), e a empresa trata dados de terceiros (seção 9.4). Mas a página já cumpre o papel de captar contato sem esta camada de confiança, e por isso é P2.

**Independent Test**: Verificar que a página tem política de privacidade e termos de uso acessíveis, identificação da empresa, e que todo depoimento, logotipo de cliente ou número exibido tem fonte ou autorização documentada.

**Acceptance Scenarios**:

1. **Given** a página publicada, **When** o visitante procura informações legais, **Then** encontra, a partir de qualquer ponto da página, links para a política de privacidade e os termos de uso.
2. **Given** a página sem nenhum cliente que tenha autorizado por escrito o uso do depoimento, **When** a seção de prova social é exibida, **Then** ela mostra o convite ao programa beta e não exibe depoimentos, logotipos ou números de clientes inventados.
3. **Given** um cliente beta que autorizou por escrito, **When** o operador publica o depoimento, **Then** a página o exibe com o nome e o cargo autorizados.
4. **Given** qualquer afirmação numérica na página (percentual, prazo, valor), **When** a página é revisada antes da publicação, **Then** cada número tem fonte documentada ou aparece claramente como exemplo ou estimativa.
5. **Given** a seção sobre segurança, **When** o visitante a lê, **Then** vê, em linguagem simples, que o serviço passa a conversa para uma pessoa quando não tem certeza, que não inventa preços e que respeita a LGPD.

---

### User Story 3 - Operador mede se a página gera conversas (Priority: P3)

O operador quer saber quantas pessoas visitam a página e quantas tocam no botão de contato, sem coletar dados pessoais dos visitantes.

**Why this priority**: Medir é útil para decidir o que ajustar, mas a página funciona sem isso. Por isso é P3.

**Independent Test**: Simular 10 visitas e 4 toques no botão. Verificar que o operador vê esses totais por dia e que nenhum dado que identifique o visitante foi guardado.

**Acceptance Scenarios**:

1. **Given** a página publicada, **When** o operador consulta as métricas, **Then** vê o total diário de visitas e de toques nos botões de contato.
2. **Given** a medição ativa, **When** um visitante usa a página, **Then** nenhum dado que o identifique (nome, telefone, e-mail, endereço de rede completo) é guardado.
3. **Given** que a medição usa algum recurso que exige consentimento, **When** o visitante abre a página pela primeira vez, **Then** vê um aviso e a medição só começa se ele consentir.

---

### Edge Cases

- Visitante com conexão lenta ou com bloqueador de rastreamento: o conteúdo principal e o botão de contato continuam acessíveis.
- Visitante sem WhatsApp instalado: tem a alternativa de abrir o WhatsApp na web ou copiar o número.
- Produto ainda indisponível na lista: aparece rotulado como "em breve", sem prometer data.
- Link de política legal quebrado ou página fora do ar: é tratado como falha de publicação; a página não pode ser divulgada sem os links funcionando.
- Tela pequena (a partir de 320 pixels de largura) ou uso só com teclado: todo o conteúdo e o botão de contato continuam usáveis.
- Cliente beta que retira a autorização do depoimento: o operador consegue remover o depoimento rapidamente.
- Número de WhatsApp da empresa ainda não ativo na data da publicação: a página não pode ser divulgada com um botão que leva a um número inexistente; o botão é testado antes de cada publicação.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A Plantão.AI DEVE ter uma página pública de uma só tela rolável, em português do Brasil, acessível por um endereço próprio e por conexão segura.
- **FR-002**: A área visível ao abrir a página DEVE trazer a proposta de valor em termos de resultado para o negócio, o nome e o lema da marca e o botão principal de contato.
- **FR-003**: A página DEVE ter uma seção de produtos com Recepcionista, Agendador, SDR, Cobrador, Pós-venda e pacote completo, cada um com nome e função em uma frase. Cada produto DEVE estar marcado como "disponível" ou "em breve" conforme o estado real do produto.
- **FR-004**: A página NÃO DEVE exibir preços nesta entrega. O detalhamento de valores é enviado após o contato.
- **FR-005**: A página DEVE ter uma seção "Como funciona" com três passos e uma seção de segurança que explique, em linguagem simples, o repasse a humano quando há dúvida, a regra de não inventar informações e o respeito à LGPD.
- **FR-006**: O botão de contato DEVE abrir uma conversa de WhatsApp com a empresa, com uma mensagem inicial preenchida que identifique a origem. DEVE haver alternativa para quem não tem o aplicativo (WhatsApp na web ou número para copiar).
- **FR-007**: O botão de contato DEVE aparecer em pelo menos três pontos da página, de modo que o visitante o alcance com um toque de qualquer seção.
- **FR-008**: A seção de prova social DEVE exibir somente depoimentos, nomes ou logotipos de clientes que tenham autorizado por escrito. Enquanto não houver, DEVE exibir o convite ao programa beta. A página NÃO DEVE exibir depoimentos, clientes ou métricas inventados.
- **FR-009**: Toda afirmação numérica da página DEVE ter fonte documentada ou estar identificada como exemplo ou estimativa.
- **FR-010**: A página DEVE ter, acessíveis de qualquer ponto, links para a política de privacidade e para os termos de uso, e DEVE identificar a empresa (nome empresarial, CNPJ quando emitido e e-mail de contato).
- **FR-011**: A página NÃO DEVE coletar dados pessoais por conta própria (sem formulários nesta entrega). A medição de visitas e de toques no botão DEVE ser agregada e NÃO DEVE guardar dados que identifiquem o visitante. Se algum recurso exigir consentimento, DEVE haver aviso e a medição só começa após aceite.
- **FR-012**: O operador DEVE poder consultar o total diário de visitas e de toques nos botões de contato.
- **FR-013**: A página DEVE ser legível e utilizável em telas a partir de 320 pixels de largura, ter contraste de texto adequado, imagens com texto alternativo e ser operável apenas com o teclado.
- **FR-014**: A página DEVE ter título, descrição e imagem de pré-visualização adequados para quando o link for compartilhado em redes sociais e no WhatsApp, e metadados básicos para mecanismos de busca.
- **FR-015**: A página DEVE seguir a identidade da marca definida na seção 9.3 do documento do projeto (nome Plantão.AI, lema, paleta azul-petróleo com destaque verde-menta ou âmbar, logotipo) e DEVE evitar o visual genérico de "IA" com gradiente roxo.
- **FR-016**: O conteúdo principal e o botão de contato DEVEM continuar acessíveis mesmo se a medição ou qualquer recurso de terceiros falhar ou for bloqueado.
- **FR-017**: O operador DEVE poder atualizar os textos, a lista de produtos e os depoimentos da página e republicá-la sem mudar o funcionamento do sistema de atendimento.

### Key Entities

- **Página pública**: conteúdo da landing page (proposta de valor, produtos com disponibilidade, como funciona, seção de segurança, prova social, links legais).
- **Produto do catálogo**: nome, função em uma frase e disponibilidade ("disponível" ou "em breve"). Segue o catálogo da seção 7.4 do documento do projeto.
- **Depoimento autorizado**: texto, autor, cargo e comprovante da autorização escrita. Só é exibido quando a autorização existe.
- **Métrica de página**: total diário de visitas e de toques no botão de contato, agregado e sem identificar o visitante.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Em um teste com 5 donos de pequenas empresas, pelo menos 4 explicam com as próprias palavras o que a Plantão.AI faz depois de 15 segundos de contato com a página, e pelo menos 4 encontram o botão de contato em até 10 segundos.
- **SC-002**: O conteúdo principal da página aparece em até 3 segundos em pelo menos 90% das cargas, em conexão móvel comum.
- **SC-003**: Do primeiro toque no botão até a conversa de WhatsApp aberta com a mensagem preenchida, o visitante precisa de no máximo 1 toque, em celular e em computador.
- **SC-004**: A página passa em uma verificação automática de acessibilidade sem problemas críticos e permanece utilizável em telas de 320 pixels de largura.
- **SC-005**: 100% das afirmações numéricas, depoimentos e logotipos na página têm fonte ou autorização documentada na revisão de publicação.
- **SC-006**: A página fica acessível por endereço próprio e conexão segura em pelo menos 99% do tempo nos primeiros 30 dias.
- **SC-007**: O operador consulta visitas e toques no botão do dia em menos de 1 minuto.
- **SC-008**: Como meta inicial de negócio, pelo menos 5 conversas de WhatsApp com a origem "página" são iniciadas nas 4 primeiras semanas após a divulgação.

## Assumptions

- A página não mostra preços porque o preço e o contrato são formalizados na semana 8 da linha do tempo. A tabela de preços em PDF (seção 9.5) é enviada depois do contato.
- A página não tem formulário, cadastro ou área de login. O contato acontece pelo WhatsApp da empresa, que pode ser atendido por uma pessoa ou pelo próprio agente da Plantão.AI como demonstração (seção 9.5). Usar o agente como demonstração é uma escolha comercial e não cria dependência desta entrega com [002-multitenancy](../002-multitenancy/spec.md): o número pode ser atendido por uma pessoa até lá.
- Dependências externas a esta especificação, a cargo do operador antes do lançamento: domínio registrado, número de WhatsApp Business da empresa, logotipo, dados legais da empresa (nome empresarial, CNPJ quando emitido, e-mail de contato) e os textos da política de privacidade e dos termos de uso, revisados por apoio jurídico (seção 9.4).
- Antes de existir cliente com autorização por escrito, a prova social é o convite ao programa beta. Os exemplos de números da seção 7.1 do documento do projeto são ilustrativos e só entram na página se forem identificados como exemplo.
- Os produtos Agendador, SDR, Cobrador e Pós-venda aparecem como "em breve" porque dependem dos Sprints 4 a 6. O Recepcionista aparece como "disponível" quando o atendimento da clínica piloto estiver em uso real; antes disso, também aparece como "em breve".
- O operador e o desenvolvedor são a mesma pessoa. Atualizar a página é uma tarefa dele, sem interface de edição para terceiros.
- A página é um só idioma (português do Brasil). A medição é mínima e agregada; o plano decide se algum recurso exige aviso de consentimento.
- Fora de escopo desta entrega: formulários e captura de leads na própria página, blog, versões em outros idiomas, testes A/B, área de login, preços públicos, chat embutido, e qualquer mudança no sistema de atendimento.
- Segue a constituição do projeto (`.specify/memory/constitution.md`), em especial os princípios IV (privacidade e LGPD) e VI (spec primeiro). Os princípios sobre dados de empresas e agentes não se aplicam, pois a página não toca dados de atendimento. Se a página ficar no mesmo repositório, o plano deve registrar a decisão em um ADR, pois a constituição exige ADR para novos diretórios de topo.
