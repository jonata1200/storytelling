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

- [x] Mapear parametros internos da aplicacao: prompt, aspect ratio, referencias, qualidade.
- [x] Criar `VeoAiFreeImageProvider`.
- [x] Validar sessao antes de gerar.
- [ ] Enviar prompt por endpoint interno ou automacao de navegador.
- [ ] Aguardar finalizacao ou detectar falha.
- [x] Baixar imagem gerada via cliente injetavel/fake.
- [x] Salvar em storage local.
- [x] Registrar provider/model no asset.

## Checklist Provider De Video

- [x] Mapear parametros internos da aplicacao: prompt, imagem inicial, aspect ratio, duracao.
- [x] Criar `VeoAiFreeVideoProvider`.
- [x] Validar sessao antes de gerar.
- [ ] Criar job remoto.
- [ ] Implementar polling com timeout longo.
- [x] Baixar MP4 final via cliente injetavel/fake.
- [x] Salvar em storage local.
- [x] Registrar estado no `GenerationJob`.

## Checklist Robustez

- [x] Detectar sessao local expirada como reconexao manual.
- [x] Detectar captcha/bloqueio como erro acionavel no cliente base.
- [x] Detectar rate limit como erro acionavel no cliente base.
- [ ] Adicionar timeout por etapa.
- [ ] Adicionar retry conservador.
- [x] Nao repetir job automaticamente se houver risco de gastar credito.

## Checklist Testes

- [x] Testar provider com cliente fake.
- [x] Testar sessao expirada.
- [x] Testar download de arquivo.
- [x] Testar erro de captcha/bloqueio.
- [x] Testar que cookies sao redigidos.
- [x] Criar smoke test real opt-in com env `RUN_VEO_FREE_SMOKE_TESTS=1`.

## Criterios De Saida

- [x] Provider experimental aparece na UI com aviso claro.
- [x] Geracao isolada funciona em teste automatizado com cliente fake.
- [x] Falhas sao compreensiveis para o usuario.
- [x] O fluxo principal da aplicacao nao fica dependente de endpoint nao descoberto.
