# Fase 4 - Migração de geração de imagens

Objetivo: migrar personagens, locais, objetos e referências visuais para
OmniRoute/OmniRouters.

## Checklist

- [ ] Confirmar endpoint final de imagem:
      `/v1/images/generations` ou rota específica OmniRouters.
- [ ] Confirmar suporte a referência de imagem para image-to-image/reference-to-image.
- [ ] Confirmar formato aceito para referências:
      `image_url`, base64, multipart ou campo próprio.
- [ ] Criar `app/providers/image/omniroute.py`.
- [ ] Mapear campos atuais:
      `prompt`, `aspect_ratio`, `resolution`, `output_format`, `references`.
- [ ] Confirmar se `n`, `resolution` e `output_format` são suportados.
- [ ] Implementar retries para parâmetros não suportados, como no provider atual.
- [ ] Confirmar formato de resposta:
      `data[0].b64_json`, URL assinada ou outro payload.
- [ ] Salvar imagem localmente com hash SHA-256 e content type correto.
- [ ] Atualizar `visual_bible/image_generation.py` para escolher OmniRoute.
- [ ] Atualizar mensagens de erro para "OmniRoute Images".
- [ ] Atualizar testes de providers de imagem.
- [ ] Criar smoke test manual com uma referência visual real.

## Pontos de atenção

- Consistência visual é crítica para a aplicação.
- Qualquer diferença no tratamento de imagens de referência pode afetar
  personagens, roupas, objetos e cenários.
- Não remover o provider OpenRouter antes de validar geração com referências.

## Critérios de aceite

- [ ] Personagem gera folha de referência com OmniRoute.
- [ ] Local gera referência consistente com OmniRoute.
- [ ] Objeto gera referência consistente com OmniRoute.
- [ ] Upload de referência continua funcionando.
- [ ] Testes de Visual Bible passam.

