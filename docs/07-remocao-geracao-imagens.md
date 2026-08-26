# Remoção da geração de imagens por IA

Data: 23/08/2026

A capacidade de gerar ou editar imagens por IA foi removida da aplicação.

## Fluxo atual

- personagens e locais permanecem como perfis canônicos exclusivamente textuais;
- o primeiro segmento de vídeo é gerado diretamente a partir do prompt;
- segmentos seguintes podem reutilizar o último frame extraído do vídeo anterior;
- imagens e referências históricas continuam legíveis como assets existentes;
- nenhum provider, modelo, chave, custo ou endpoint de geração de imagens permanece ativo.

## Componentes removidos

- providers OpenRouter e mock de imagens e seus contratos;
- geração de referências da biblioteca visual;
- geração de frames inicial/final por modelo de imagem;
- pipeline legado de storyboard baseado em imagens;
- configuração global e por projeto de modelo/provider de imagem;
- custos e readiness do canal de imagem;
- controles de UI e testes exclusivos da funcionalidade removida.

## Banco de dados

A migração `202608230032` remove `image_model` e `image_resolution` de
`project_production_settings`.
Tabelas e assets históricos de referências visuais foram preservados para não destruir conteúdo
existente. Eles não são usados como fonte de novas gerações.
