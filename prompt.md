Você é um arquiteto de software sênior, engenheiro de IA generativa e especialista em pipelines de produção audiovisual.

Sua tarefa é projetar e implementar uma aplicação completa, escrita prioritariamente em Python, para criação assistida por IA de histórias emocionantes em vídeo vertical para redes sociais.

Não construa apenas uma interface que envia prompts para modelos. Construa um sistema de produção audiovisual estruturado, versionado, consistente, recuperável e orientado por etapas.

# 1. Objetivo do produto

Criar uma aplicação que permita produzir histórias completas para vídeos verticais, especialmente Facebook Reels, com duração configurável entre 3 e 8 minutos.

O sistema deve conduzir o usuário pelas seguintes etapas:

1. Criação e seleção da ideia.
2. Desenvolvimento da premissa.
3. Estruturação narrativa.
4. Criação do roteiro.
5. Definição de personagens, locais e objetos.
6. Criação de referências visuais com múltiplas vistas.
7. Criação da lista de cenas e planos.
8. Geração dos storyboards.
9. Planejamento da produção audiovisual.
10. Geração dos clipes de vídeo.
11. Geração da narração, diálogos, trilha e efeitos.
12. Montagem automática.
13. Criação de legendas.
14. Verificação de consistência.
15. Revisão humana.
16. Exportação do vídeo final.

O principal diferencial do sistema deve ser a manutenção da consistência narrativa, visual, temporal e sonora durante toda a história.

# 2. Princípios obrigatórios

Implemente o sistema seguindo estes princípios:

* Tudo deve ser salvo como dados estruturados.
* Nenhuma etapa importante pode depender apenas do histórico de um chat.
* Cada projeto deve possuir uma “Bíblia da História”.
* Personagens, locais, objetos, vozes, roupas e estilos devem possuir identificadores permanentes.
* Toda geração deve registrar prompt, modelo, provedor, parâmetros, referências, custo estimado, versão e resultado.
* O usuário deve poder aprovar, rejeitar, editar ou regenerar cada etapa.
* Uma alteração deve invalidar apenas os elementos dependentes dela.
* Não regenere todo o projeto quando apenas uma cena for alterada.
* Os provedores de IA devem ser substituíveis.
* O sistema deve possuir processamento assíncrono, retentativas e recuperação de falhas.
* A aplicação deve priorizar baixo custo, previsibilidade e consistência.
* O sistema deve ser preparado para funcionamento como SaaS multiusuário, mesmo que o primeiro MVP seja executado localmente.

# 3. Stack tecnológica

Use a seguinte stack inicial:

## Backend e interface

* Python 3.12 ou superior.
* FastAPI para API interna e externa.
* NiceGUI para a interface web escrita em Python.
* Pydantic para validação de dados.
* SQLAlchemy 2 para persistência.
* Alembic para migrações.
* PostgreSQL como banco principal.
* pgvector para embeddings e busca semântica.
* Redis para cache, locks e filas.
* Celery para tarefas assíncronas.
* WebSockets ou Server-Sent Events para atualização do progresso.
* FFmpeg para composição e renderização.
* Pillow e OpenCV para processamento de imagens.
* Docker e Docker Compose para ambiente local.

## Armazenamento

Crie uma interface de armazenamento compatível com:

* Sistema de arquivos local durante o desenvolvimento.
* Amazon S3.
* Cloudflare R2.
* Outros serviços compatíveis com S3.

Nunca armazene arquivos pesados diretamente no PostgreSQL. Salve apenas metadados, hashes e caminhos.

## IA

Crie interfaces separadas para:

* Modelo de linguagem.
* Geração de imagens.
* Edição de imagens.
* Geração de vídeos.
* Síntese de voz.
* Transcrição e alinhamento.
* Música.
* Efeitos sonoros.
* Embeddings.
* Moderação.

Não acople a lógica da aplicação a um modelo específico.

# 4. Arquitetura

Comece com um modular monolith. Não crie microsserviços prematuramente.

Organize o projeto em módulos semelhantes a:

```text
app/
  api/
  ui/
  core/
  config/
  auth/
  projects/
  storytelling/
  story_bible/
  continuity/
  characters/
  locations/
  props/
  scripts/
  scenes/
  shots/
  storyboards/
  generation/
  providers/
    llm/
    image/
    video/
    speech/
    music/
    embeddings/
  workflows/
  approvals/
  assets/
  media/
  rendering/
  subtitles/
  costs/
  moderation/
  observability/
  database/
  tests/
```

Separe claramente:

* Domínio.
* Casos de uso.
* Infraestrutura.
* Provedores externos.
* Interface.
* Processamento assíncrono.

A lógica central não pode importar diretamente SDKs de provedores de IA. Use interfaces, protocolos ou classes abstratas.

# 5. Fluxo do projeto

Cada projeto deve funcionar como uma máquina de estados.

Estados principais:

```text
DRAFT
IDEA_GENERATION
IDEA_APPROVAL
STORY_DESIGN
STORY_APPROVAL
SCRIPT_GENERATION
SCRIPT_APPROVAL
VISUAL_BIBLE_GENERATION
VISUAL_BIBLE_APPROVAL
STORYBOARD_GENERATION
STORYBOARD_APPROVAL
PRODUCTION_PLANNING
VIDEO_GENERATION
VIDEO_REVIEW
AUDIO_GENERATION
ASSEMBLY
QUALITY_CONTROL
FINAL_APPROVAL
COMPLETED
FAILED
ARCHIVED
```

O usuário pode voltar para uma etapa anterior. Quando isso ocorrer, calcule quais artefatos posteriores ficaram desatualizados.

Use estados adicionais para cada artefato:

```text
PENDING
GENERATING
READY_FOR_REVIEW
APPROVED
REJECTED
STALE
FAILED
CANCELLED
```

# 6. Aprovação humana

O sistema deve possuir aprovação humana obrigatória nos seguintes pontos:

1. Ideia escolhida.
2. Premissa e estrutura narrativa.
3. Roteiro.
4. Bíblia visual.
5. Storyboards.
6. Plano de produção.
7. Primeiro clipe de cada personagem principal.
8. Vídeo montado.
9. Exportação final.

Em cada tela de aprovação, permita:

* Aprovar.
* Editar manualmente.
* Solicitar regeneração.
* Selecionar trechos para regenerar.
* Comparar versões.
* Escrever instruções adicionais.
* Restaurar uma versão anterior.
* Marcar o artefato como bloqueado.

Artefatos bloqueados não podem ser alterados automaticamente.

# 7. Motor de storytelling

Implemente um módulo especializado em histórias emocionantes para vídeos verticais.

O usuário deve informar:

* Tema.
* Público.
* Gênero.
* Emoção principal.
* Intensidade emocional.
* Tipo de final.
* Idioma.
* País ou contexto cultural.
* Duração desejada.
* Restrições.
* Presença ou ausência de narrador.
* Estilo visual.
* Objetivo do conteúdo.
* Chamada para ação opcional.

O sistema deve gerar diferentes ideias contendo:

* Título provisório.
* Gancho inicial.
* Premissa.
* Protagonista.
* Desejo do protagonista.
* Necessidade emocional.
* Conflito.
* Obstáculos.
* Riscos.
* Reviravolta.
* Clímax.
* Resolução.
* Emoção final.
* Potencial de retenção.
* Riscos de clichê.
* Complexidade de produção.
* Custo estimado de produção.

## Estrutura narrativa

O motor deve poder trabalhar com:

* Estrutura de três atos.
* Arco de transformação.
* Problema, tentativa, agravamento e resolução.
* Mistério e revelação.
* Tragédia e redenção.
* Sacrifício.
* Injustiça e reparação.
* Promessa e payoff.
* Open loops.
* Setup e payoff.
* Escalada de riscos.
* Reviravoltas justificadas.

Para vídeos curtos e verticais, aplique:

* Gancho nos primeiros segundos.
* Contexto mínimo.
* Entrada rápida no conflito.
* Microganchos durante a narrativa.
* Mudanças visuais frequentes.
* Revelação progressiva de informações.
* Crescimento emocional.
* Ponto de não retorno.
* Clímax claro.
* Payoff proporcional à promessa inicial.
* Encerramento emocional forte.

Evite:

* Introduções longas.
* Exposição excessiva.
* Personagens sem objetivo.
* Reviravoltas aleatórias.
* Repetição de informações.
* Cenas que não alteram a história.
* Final sem payoff.

# 8. Estrutura temporal

Calcule a duração a partir da narração e dos diálogos.

Não estime a duração somente pelo número de cenas.

O sistema deve:

1. Gerar o roteiro.
2. Calcular a quantidade aproximada de palavras.
3. Gerar áudio provisório ou estimar o ritmo.
4. Criar uma timeline.
5. Dividir a história em cenas.
6. Dividir as cenas em planos.
7. Ajustar a duração total para o alvo de 3 a 8 minutos.

Cada plano deve possuir:

* Duração.
* Texto narrado correspondente.
* Diálogo correspondente.
* Ação.
* Emoção.
* Composição visual.
* Movimento de câmera.
* Movimento dos personagens.
* Ambiente.
* Som.
* Transição.
* Tipo de geração.

# 9. Estratégia eficiente de produção

Não gere todos os segundos usando modelos caros de text-to-video.

Implemente um planejador que classifique cada plano como:

```text
AI_VIDEO
IMAGE_TO_VIDEO
ANIMATED_STILL
MULTIPLANE_PARALLAX
CAMERA_PAN
CAMERA_ZOOM
LOOPED_VIDEO
TRANSITION
TEXT_CARD
REUSED_ASSET
```

Use vídeo generativo completo principalmente em:

* Momentos de ação.
* Expressões emocionais importantes.
* Entradas de personagens.
* Reviravoltas.
* Clímax.
* Planos que exigem movimento complexo.

Use imagens animadas em:

* Planos de estabelecimento.
* Objetos.
* Fotografias.
* Memórias.
* Cenas narradas sem movimento complexo.
* Reações discretas.
* Transições.

O planejador deve comparar:

* Importância narrativa.
* Necessidade de movimento.
* Risco de inconsistência.
* Custo.
* Tempo de geração.
* Disponibilidade de referências.
* Duração.

Mostre ao usuário o custo estimado antes de iniciar a produção.

# 10. Bíblia da História

Cada projeto deve possuir uma Story Bible estruturada e versionada.

Inclua:

```json
{
  "title": "",
  "logline": "",
  "theme": "",
  "genre": "",
  "tone": "",
  "target_emotion": "",
  "audience": "",
  "world_rules": [],
  "visual_style": {},
  "narrative_rules": [],
  "forbidden_elements": [],
  "characters": [],
  "locations": [],
  "props": [],
  "timeline": [],
  "relationships": [],
  "continuity_rules": [],
  "audio_style": {},
  "export_profile": {}
}
```

A Story Bible aprovada deve ser usada automaticamente em todos os prompts posteriores.

Nunca dependa do modelo para lembrar informações fornecidas em chamadas anteriores.

# 11. Consistência de personagens

Cada personagem deve possuir uma ficha canônica:

* ID permanente.
* Nome.
* Papel narrativo.
* Idade aparente.
* Altura aproximada.
* Tipo físico.
* Formato do rosto.
* Tom de pele.
* Olhos.
* Sobrancelhas.
* Nariz.
* Boca.
* Cabelo.
* Marcas particulares.
* Postura.
* Linguagem corporal.
* Roupa base.
* Variações de roupa.
* Acessórios.
* Paleta.
* Voz.
* Sotaque.
* Personalidade.
* Medos.
* Objetivos.
* Estado emocional inicial.
* Arco emocional.
* Restrições visuais.

Crie para cada personagem:

* Retrato frontal.
* Perfil esquerdo.
* Perfil direito.
* Vista de costas.
* Corpo inteiro.
* Folha de expressões.
* Folha de poses.
* Referência de escala.
* Variações de roupa aprovadas.

Salve as imagens aprovadas como referências canônicas.

Crie um `character_fingerprint` contendo dados estruturados, prompt canônico, embeddings, hashes perceptuais e referências visuais.

# 12. Consistência de locais e objetos

Cada local deve possuir:

* ID.
* Descrição.
* Planta conceitual.
* Entradas e saídas.
* Distribuição de móveis.
* Materiais.
* Paleta.
* Iluminação.
* Horário.
* Clima.
* Pontos de câmera.
* Regras espaciais.
* Imagens de referência.

Cada objeto relevante deve possuir:

* ID.
* Dimensões aproximadas.
* Material.
* Cor.
* Estado.
* Proprietário.
* Importância narrativa.
* Localização ao longo da história.
* Imagens em múltiplos ângulos.

# 13. Continuity Ledger

Implemente um registro de continuidade por cena e plano.

Para cada plano, acompanhe:

* Personagens presentes.
* Roupa.
* Acessórios.
* Ferimentos.
* Sujeira.
* Cabelo.
* Emoção.
* Posição.
* Direção do olhar.
* Objetos carregados.
* Localização dos objetos.
* Horário.
* Clima.
* Iluminação.
* Estado do ambiente.
* Eventos anteriores necessários.
* Eventos posteriores preparados.

Antes de gerar um plano, compile seu estado inicial usando o plano anterior.

Depois da geração, execute uma verificação automática de continuidade.

Crie alertas como:

* Roupa incompatível.
* Objeto desaparecido.
* Personagem duplicado.
* Mudança indevida de idade.
* Mudança de cabelo.
* Mudança de arquitetura.
* Mudança de horário.
* Ferimento ausente.
* Direção espacial incoerente.
* Emoção incompatível.
* Ação impossível em relação ao plano anterior.

Permita que o usuário aceite a divergência como intencional.

# 14. Compilador de prompts

Não espalhe prompts em strings aleatórias pelo código.

Crie um sistema versionado de templates de prompt.

Cada prompt final deve ser compilado a partir de:

1. Objetivo da tarefa.
2. Bíblia da história.
3. Ficha dos personagens.
4. Ficha do local.
5. Ficha dos objetos.
6. Estado de continuidade.
7. Descrição do plano.
8. Estilo visual.
9. Restrições.
10. Capacidades do provedor.
11. Referências visuais.
12. Prompt negativo.
13. Formato de saída.

Salve:

* Template utilizado.
* Versão.
* Variáveis.
* Prompt final.
* Resposta.
* Modelo.
* Parâmetros.
* Seed, quando suportada.
* Imagens de referência.
* Data.
* Custo.
* Tempo de geração.

# 15. Adaptadores de IA

Defina interfaces semelhantes a:

```python
class LLMProvider(Protocol):
    async def generate_structured(self, request: LLMRequest) -> LLMResult:
        ...

class ImageProvider(Protocol):
    async def generate(self, request: ImageGenerationRequest) -> ImageResult:
        ...

    async def edit(self, request: ImageEditRequest) -> ImageResult:
        ...

class VideoProvider(Protocol):
    async def generate_from_text(self, request: VideoRequest) -> VideoResult:
        ...

    async def generate_from_image(self, request: VideoRequest) -> VideoResult:
        ...

    async def get_status(self, external_job_id: str) -> JobStatus:
        ...

    async def cancel(self, external_job_id: str) -> None:
        ...

class SpeechProvider(Protocol):
    async def synthesize(self, request: SpeechRequest) -> SpeechResult:
        ...
```

Implemente inicialmente:

* Um provider mock para testes.
* Um provider de linguagem configurável.
* Um provider de imagem configurável.
* Pelo menos um provider comercial de vídeo.
* Um provider de voz.

Prepare adaptadores opcionais para:

* Runway.
* Luma.
* Google Veo.
* Outros provedores adicionados posteriormente.

Crie um registro de capacidades:

```python
ProviderCapabilities(
    text_to_video=True,
    image_to_video=True,
    reference_images=True,
    character_reference=False,
    first_frame=True,
    last_frame=False,
    native_audio=False,
    supported_durations=[],
    supported_aspect_ratios=[],
    max_reference_images=0
)
```

O orquestrador deve escolher o provedor com base em:

* Capacidade.
* Qualidade desejada.
* Custo.
* prazo.
* disponibilidade.
* limite de concorrência.
* formato.
* necessidade de referências.

# 16. Jobs assíncronos

Toda operação demorada deve ser executada em background:

* Geração de imagens.
* Geração de vídeo.
* Síntese de voz.
* Renderização.
* Upload.
* Análise de consistência.
* Transcrição.
* Geração de legendas.

Cada job deve possuir:

* ID interno.
* ID externo.
* Tipo.
* Status.
* Progresso.
* Número de tentativas.
* Erro.
* Provedor.
* Custo.
* Data de criação.
* Data de conclusão.
* Artefato de origem.
* Artefato resultante.

Implemente:

* Retentativa com exponential backoff.
* Idempotência.
* Cancelamento.
* Timeout.
* Rate limiting.
* Circuit breaker por provedor.
* Webhook quando suportado.
* Polling quando necessário.
* Dead-letter queue.
* Locks para impedir geração duplicada.

# 17. Modelo de dados

Crie entidades para, no mínimo:

* User.
* Workspace.
* Project.
* ProjectVersion.
* StoryIdea.
* StoryBible.
* Character.
* CharacterVersion.
* CharacterLook.
* Location.
* LocationVersion.
* Prop.
* PropVersion.
* Script.
* ScriptVersion.
* Scene.
* Shot.
* ContinuityState.
* StoryboardFrame.
* Asset.
* AssetVersion.
* GenerationJob.
* PromptTemplate.
* PromptExecution.
* Approval.
* Comment.
* ProviderConfiguration.
* CostEntry.
* Timeline.
* AudioTrack.
* SubtitleTrack.
* RenderJob.
* Export.

Use UUIDs.

Implemente soft delete, timestamps, versionamento e auditoria.

# 18. Storyboards

O storyboard deve ser gerado a partir dos planos, não diretamente do roteiro completo.

Cada quadro deve mostrar:

* Personagens corretos.
* Composição.
* Enquadramento.
* Pose.
* Emoção.
* Local.
* Objetos.
* Iluminação.
* Movimento sugerido.
* Duração.
* Narração ou diálogo.
* Número da cena e do plano.

A tela de storyboard deve permitir:

* Visualização em sequência.
* Visualização em grade.
* Reordenação.
* Edição.
* Regeneração individual.
* Duplicação.
* Comparação de versões.
* Aprovação em lote.
* Reprodução como animatic.

Crie um animatic usando quadros, narração provisória e duração dos planos antes de gerar os vídeos caros.

# 19. Produção de vídeo

A geração deve ocorrer plano a plano.

Para cada plano:

1. Carregue a Story Bible.
2. Carregue os ativos aprovados.
3. Carregue o Continuity Ledger.
4. Compile o prompt.
5. Escolha o provedor.
6. Envie as referências.
7. Gere uma prévia quando possível.
8. Armazene o resultado.
9. Execute análise automática.
10. Envie para aprovação.
11. Atualize o estado final do plano.

Permita gerar múltiplas variações e selecionar uma como oficial.

Nunca substitua silenciosamente um ativo aprovado.

# 20. Áudio

Implemente:

* Narração.
* Diálogos.
* Voz permanente por personagem.
* Controle de velocidade.
* Emoção.
* Pausas.
* Pronúncia personalizada.
* Música.
* Ambiência.
* Efeitos sonoros.
* Mixagem.
* Normalização.

Cada personagem deve possuir um `voice_profile_id`.

A voz selecionada deve permanecer igual durante toda a história.

Gere timestamps de palavras ou frases para:

* Sincronização.
* Legendas.
* Cortes.
* Mudanças visuais.
* Lip sync futuro.

O usuário deve poder substituir qualquer faixa manualmente.

# 21. Montagem

Crie um compositor baseado em timeline.

Cada item da timeline deve conter:

* Início.
* Fim.
* Camada.
* Arquivo.
* Corte.
* Velocidade.
* Opacidade.
* Escala.
* Posição.
* Transição.
* Áudio.
* Legenda.
* Efeitos.

Use FFmpeg para:

* Concatenar planos.
* Ajustar resolução.
* Aplicar pan e zoom.
* Criar parallax simples.
* Adicionar transições.
* Mixar áudio.
* Inserir legendas.
* Normalizar volume.
* Gerar thumbnails.
* Exportar o vídeo.

Perfil inicial de exportação:

* Orientação vertical.
* Proporção 9:16.
* Resolução padrão 1080 × 1920.
* FPS configurável.
* Codec H.264.
* Áudio AAC.
* Bitrate configurável.
* Safe areas para texto.
* Legendas opcionais embutidas.
* Arquivo SRT separado.

Não fixe regras de uma plataforma diretamente no código. Crie perfis de exportação configuráveis.

# 22. Controle de custos

Antes de executar um lote, apresente:

* Provedor.
* Modelo.
* Quantidade de gerações.
* Duração.
* Custo estimado.
* Custo acumulado.
* Faixa de incerteza.
* Alternativas mais baratas.

Implemente:

* Limite por projeto.
* Limite diário.
* Limite por usuário.
* Confirmação acima de um valor.
* Seleção entre modo econômico, equilibrado e qualidade máxima.
* Registro do custo real.
* Cache por hash de requisição.
* Reutilização de resultados idênticos.

# 23. Interface

Crie as seguintes telas:

1. Login.
2. Dashboard.
3. Novo projeto.
4. Briefing.
5. Ideias.
6. Estrutura narrativa.
7. Roteiro.
8. Story Bible.
9. Personagens.
10. Locais.
11. Objetos.
12. Cenas e planos.
13. Storyboard.
14. Animatic.
15. Plano de produção.
16. Fila de geração.
17. Revisão de clipes.
18. Áudio.
19. Timeline.
20. Controle de qualidade.
21. Custos.
22. Exportação.
23. Configuração de provedores.

A tela principal do projeto deve mostrar um pipeline visual com:

* Estado de cada etapa.
* Quantidade de itens pendentes.
* Itens aguardando aprovação.
* Erros.
* Custos.
* Progresso.
* Dependências desatualizadas.

# 24. Segurança

Implemente:

* Variáveis de ambiente.
* Segredos criptografados.
* Nunca enviar chaves ao frontend.
* Autenticação.
* Autorização por workspace.
* Logs sem dados sensíveis.
* URLs assinadas para arquivos.
* Validação de uploads.
* Limites de tamanho.
* Moderação.
* Registro de autoria e origem dos ativos.
* Política de retenção.
* Exclusão de projeto.
* Proteção contra prompt injection em textos fornecidos pelo usuário.

# 25. Observabilidade

Implemente:

* Logs estruturados.
* Correlation ID.
* Métricas.
* Rastreamento de jobs.
* Tempo por geração.
* Taxa de falha por provedor.
* Custo por projeto.
* Custo por minuto de vídeo.
* Alertas de jobs travados.
* Painel de saúde dos provedores.

# 26. Testes

Crie:

* Testes unitários.
* Testes de integração.
* Testes de API.
* Testes de banco.
* Testes dos adaptadores.
* Testes de idempotência.
* Testes de invalidação de dependências.
* Testes da máquina de estados.
* Testes de compilação de prompts.
* Testes de continuidade.
* Testes de renderização com arquivos pequenos.
* Mocks das APIs externas.

Nenhum teste automatizado deve consumir APIs pagas por padrão.

# 27. MVP

O primeiro MVP funcional deve permitir:

1. Criar um projeto.
2. Informar o briefing.
3. Gerar três ideias.
4. Aprovar uma ideia.
5. Gerar a Story Bible.
6. Gerar o roteiro.
7. Editar e aprovar o roteiro.
8. Criar personagens.
9. Gerar imagens de referência.
10. Criar cenas e planos.
11. Gerar storyboards.
12. Criar um animatic.
13. Aprovar planos.
14. Gerar clipes usando um provider comercial.
15. Gerar narração.
16. Montar uma timeline.
17. Renderizar um vídeo vertical.
18. Exportar MP4 e SRT.
19. Registrar custos.
20. Retomar projetos interrompidos.

# 28. Fases de implementação

Implemente nesta ordem:

## Fase 1 — Fundação

* Estrutura do repositório.
* Configuração.
* Docker Compose.
* PostgreSQL.
* Redis.
* FastAPI.
* NiceGUI.
* SQLAlchemy.
* Alembic.
* Autenticação básica.
* Testes.
* CI.

## Fase 2 — Domínio

* Entidades.
* Repositórios.
* Máquina de estados.
* Versionamento.
* Aprovações.
* Grafo de dependências.
* Assets.
* Custos.

## Fase 3 — Narrativa

* Briefing.
* Ideias.
* Story Bible.
* Roteiro.
* Cenas.
* Planos.
* Templates de prompt.
* Provider mock de linguagem.

## Fase 4 — Bíblia visual

* Personagens.
* Locais.
* Objetos.
* Imagens de referência.
* Aprovação.
* Consistência.
* Provider de imagem.

## Fase 5 — Storyboard

* Shot list.
* Storyboard.
* Animatic.
* Timeline preliminar.
* Narração provisória.

## Fase 6 — Vídeo

* Interface de VideoProvider.
* Integração com um provedor comercial.
* Jobs.
* Polling ou webhook.
* Revisão de clipes.
* Retentativas.
* Custos.

## Fase 7 — Finalização

* Voz.
* Legendas.
* Música.
* Efeitos.
* Timeline.
* FFmpeg.
* Exportação.

## Fase 8 — Qualidade

* Continuity Ledger.
* Verificações automáticas.
* Observabilidade.
* Otimização.
* Segurança.
* Testes end-to-end.

# 29. Regras para implementação pelo Codex

Ao implementar:

* Não gere todo o sistema em um único arquivo.
* Não use código fictício quando uma implementação simples for possível.
* Não deixe funções centrais apenas com `pass`.
* Não coloque lógica de negócio nas rotas.
* Não coloque SDKs externos dentro do domínio.
* Use type hints.
* Use docstrings onde agregarem valor.
* Use `async` corretamente.
* Valide dados com Pydantic.
* Crie migrações.
* Crie testes junto com cada módulo.
* Documente comandos de execução.
* Mantenha um arquivo `ARCHITECTURE.md`.
* Mantenha um arquivo `DECISIONS.md` com ADRs.
* Mantenha um arquivo `PROGRESS.md`.
* Atualize o README a cada fase.
* Use lint, formatter e type checker.
* Evite abstrações desnecessárias.
* Prefira código claro.
* Não exponha segredos.
* Não faça chamadas reais a APIs durante os testes.

Ferramentas recomendadas:

* Ruff.
* Pyright ou mypy.
* Pytest.
* pytest-asyncio.
* pre-commit.
* GitHub Actions.

# 30. Critérios de aceitação

O sistema estará correto quando:

* Um projeto puder ser interrompido e retomado.
* Cada artefato possuir versões.
* Toda geração puder ser auditada.
* O usuário puder aprovar cada etapa.
* Alterar uma roupa não invalidar partes não relacionadas.
* Alterar o roteiro marcar cenas dependentes como desatualizadas.
* Um personagem aprovado permanecer visualmente referenciado em todos os planos.
* Um objeto importante não desaparecer sem justificativa.
* Jobs duplicados forem evitados.
* Falhas externas puderem ser retomadas.
* O custo for mostrado antes da geração.
* O vídeo final puder ser renderizado verticalmente.
* As legendas estiverem sincronizadas.
* Nenhuma chave de API aparecer no frontend ou nos logs.
* Os testes funcionarem sem consumir créditos.

# 31. Primeira execução

Comece agora pela Fase 1.

Antes de escrever código:

1. Apresente resumidamente a arquitetura escolhida.
2. Liste as principais decisões e trade-offs.
3. Crie a árvore de diretórios.
4. Crie o `docker-compose.yml`.
5. Crie a configuração do projeto.
6. Crie a aplicação FastAPI.
7. Crie uma interface NiceGUI inicial.
8. Configure PostgreSQL, Redis, Celery e Alembic.
9. Crie endpoints de health check.
10. Crie testes básicos.
11. Crie README com instruções de execução.

Depois disso, implemente o domínio inicial de projetos e artefatos versionados.

Trabalhe de forma incremental. Ao final de cada fase:

* Execute os testes.
* Corrija os erros.
* Mostre os arquivos criados e alterados.
* Explique decisões importantes.
* Atualize `PROGRESS.md`.
* Indique claramente o próximo passo.

Quando alguma API externa ainda não estiver configurada, use providers mockados e mantenha o sistema funcional.
