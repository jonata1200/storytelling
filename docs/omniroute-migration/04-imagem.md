# Fase 4 - Migração de geração de imagens

Objetivo: migrar personagens, locais, objetos e referências visuais para
OmniRoute/OmniRouters.

## Checklist

- [x] Confirmar endpoint final de imagem:
      `/v1/images/generations`.
- [x] Confirmar suporte a referência de imagem para image-to-image/reference-to-image.
- [x] Confirmar formato aceito para referências:
      `input_references` com itens `image_url` em data URL/base64, mantendo o
      contrato usado pela aplicação para preservar consistência visual.
- [x] Criar `app/providers/image/omniroute.py`.
- [x] Mapear campos atuais:
      `prompt`, `aspect_ratio`, `resolution`, `output_format`, `references`.
- [x] Confirmar se `n`, `resolution` e `output_format` são suportados.
- [x] Implementar retries para parâmetros não suportados, como no provider atual.
- [x] Confirmar formato de resposta:
      `data[0].b64_json`, `data[0].url` ou `data[0].image_url`.
- [x] Salvar imagem localmente com hash SHA-256 e content type correto.
- [x] Atualizar `visual_bible/image_generation.py` para escolher OmniRoute.
- [x] Atualizar mensagens de erro para "OmniRoute Images".
- [x] Atualizar testes de providers de imagem.
- [x] Criar smoke test manual com uma referência visual real.

## Pontos De Atenção

- Consistência visual é crítica para a aplicação.
- Qualquer diferença no tratamento de imagens de referência pode afetar
  personagens, roupas, objetos e cenários.
- Não remover o provider OpenRouter antes de validar geração com referências.

## Critérios De Aceite

- [x] Personagem usa OmniRoute para gerar folha de referência quando
      `IMAGE_PROVIDER=omniroute`.
- [x] Local usa OmniRoute para gerar referência consistente quando
      `IMAGE_PROVIDER=omniroute`.
- [x] Objeto usa OmniRoute para gerar referência consistente quando
      `IMAGE_PROVIDER=omniroute`.
- [x] Upload de referência continua funcionando e é convertido para data URL.
- [x] Testes de Visual Bible passam.
- [ ] Smoke real com API OmniRoute executado contra uma referência visual real.

## Resultado

- Provider `OmniRouteImageProvider` criado com endpoint `/images/generations`.
- Visual Bible e Storyboard escolhem OmniRoute quando o provider de imagem está
  configurado como `omniroute`.
- Assets OmniRoute são gravados em `omniroute_images` e `omniroute_storyboards`.
- Testes adicionados em `tests/test_omniroute_provider.py` e
  `tests/test_omniroute_smoke.py`.
- O smoke real fica protegido por `OMNIROUTE_SMOKE=1` e `OMNIROUTE_API_KEY` para
  evitar chamadas pagas acidentais.
