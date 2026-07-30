# Fase 06 - Provider Experimental Veo AI Free Para Imagem E Video

## Objetivo

Criar providers experimentais para imagem e video usando a conexao Veo AI Free
validada na fase anterior.

## Escopo

- Geracao de imagem.
- Geracao de video.
- Polling ou acompanhamento de fila.
- Download do arquivo gerado.
- Registro de asset/job na aplicacao.

## Regras De Produto

- O provider deve aparecer como `experimental`.
- Jobs em lote devem exigir confirmacao.
- Falhas devem orientar reconexao manual quando sessao expirar.
- Nao deve existir tentativa de burlar bloqueios do site.
- Deve haver alternativa para desabilitar esse provider por env/config.

## Arquivos Propostos

```text
app/providers/image/veo_ai_free.py
app/providers/video/veo_ai_free.py
app/providers/veo_free/session.py
app/providers/veo_free/browser.py
tests/test_veo_ai_free_session.py
tests/test_veo_ai_free_provider.py
```

## Checklist Provider De Imagem

- [ ] Mapear parametros do site: prompt, aspect ratio, referencias, qualidade.
- [ ] Criar `VeoAiFreeImageProvider`.
- [ ] Validar sessao antes de gerar.
- [ ] Enviar prompt por endpoint interno ou automacao de navegador.
- [ ] Aguardar finalizacao ou detectar falha.
- [ ] Baixar imagem gerada.
- [ ] Salvar em storage local.
- [ ] Registrar provider/model no asset.

## Checklist Provider De Video

- [ ] Mapear parametros do site: prompt, imagem inicial, aspect ratio, duracao.
- [ ] Criar `VeoAiFreeVideoProvider`.
- [ ] Validar sessao antes de gerar.
- [ ] Criar job remoto.
- [ ] Implementar polling com timeout longo.
- [ ] Baixar MP4 final.
- [ ] Salvar em storage local.
- [ ] Registrar estado no `GenerationJob`.

## Checklist Robustez

- [ ] Detectar `401/403` como sessao expirada ou bloqueada.
- [ ] Detectar captcha e retornar erro acionavel.
- [ ] Detectar rate limit.
- [ ] Adicionar timeout por etapa.
- [ ] Adicionar retry conservador.
- [ ] Nao repetir job automaticamente se houver risco de gastar credito.

## Checklist Testes

- [ ] Testar provider com cliente fake.
- [ ] Testar sessao expirada.
- [ ] Testar download de arquivo.
- [ ] Testar erro de captcha/bloqueio.
- [ ] Testar que cookies sao redigidos.
- [ ] Criar smoke test real opt-in com env `RUN_VEO_FREE_SMOKE_TESTS=1`.

## Criterios De Saida

- [ ] Provider experimental aparece na UI com aviso claro.
- [ ] Geracao isolada funciona em teste manual.
- [ ] Falhas sao compreensiveis para o usuario.
- [ ] O fluxo principal da aplicacao nao fica dependente desse provider.
