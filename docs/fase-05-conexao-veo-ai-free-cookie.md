# Fase 05 - Conexao Experimental Veo AI Free Via Cookie

## Objetivo

Criar uma conexao experimental com Veo AI Free usando cookie/sessao do navegador,
sem tratar isso como API oficial e sem depender disso para operacao critica.

## Aviso De Risco

Esta fase depende de endpoints internos ou comportamento do site. A integracao pode
quebrar sem aviso, expirar por sessao, ser bloqueada por captcha/rate limit ou nao
ser permitida pelos termos do servico. Nao implementar bypass de captcha,
Cloudflare, fingerprint, paywall ou limite de uso.

## Arquitetura Proposta

```text
app/providers/veo_free/session.py
app/providers/veo_free/browser.py
app/providers/veo_free/types.py
```

Servicos:

- `VeoFreeSessionStore`: salva cookies/tokens localmente.
- `VeoFreeSessionValidator`: verifica se a sessao ainda esta conectada.
- `VeoFreeBrowserClient`: executa operacoes via navegador controlado quando necessario.

## Armazenamento

```text
.runtime/veo_free/session.json
```

Regras:

- [x] Nunca versionar `.runtime/veo_free/`.
- [x] Redigir cookies/tokens em logs.
- [x] Permitir apagar sessao pela UI.
- [ ] Idealmente criptografar localmente quando houver chave de app.

## Checklist Descoberta Tecnica

- [ ] Abrir Veo AI Free manualmente no navegador.
- [ ] Identificar se ha login ou sessao anonima.
- [ ] Inspecionar chamadas de rede no DevTools.
- [ ] Verificar se existe endpoint leve para status da conta/sessao.
- [ ] Verificar se ha CSRF token.
- [ ] Verificar se cookies sao amarrados a user-agent/IP/fingerprint.
- [ ] Verificar se ha captcha ou protecao anti-automacao.
- [ ] Documentar endpoints internos encontrados sem expor tokens.

## Checklist Validador De Sessao

- [x] Criar funcao `save_cookie_bundle`.
- [x] Criar funcao `validate_session`.
- [x] Criar funcao `clear_session`.
- [x] Retornar estados: `connected`, `expired`, `blocked`, `unknown`.
- [x] Criar readiness `veo_ai_free_session`.
- [x] Adicionar UI para colar/importar cookie.
- [x] Exibir aviso de integracao experimental.

## Criterios De Saida

- [x] A aplicacao consegue dizer se a sessao Veo AI Free parece valida.
- [x] Sessao expirada pede reconexao manual.
- [x] Nenhum token/cookie aparece em log, evento ou teste.
- [x] Nenhum job de imagem/video depende ainda dessa integracao.
