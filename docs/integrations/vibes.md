# Integração Vibes

O Vibes é o provider alvo de vídeo. Em agosto de 2026, a Meta apresenta geração,
animação de imagens, música e remix no produto Vibes, em `meta.ai` e no app Meta AI,
mas não publica uma API de geração para desenvolvedores.

Por segurança, `VIBES_INTEGRATION_MODE=api` falha explicitamente. A aplicação não
descobre nem chama endpoints internos. O modo browser usa uma porta isolada em
`app/providers/video/vibes_browser.py`; o backend Playwright só deve ser habilitado
depois de autorizado e validado contra a interface disponível para a conta.

```env
VIDEO_PROVIDER=vibes
VIBES_INTEGRATION_MODE=browser
VIBES_VIDEO_MODEL=vibes
VIBES_BROWSER_PROFILE_PATH=./runtime/browser_profiles/vibes
VIBES_BROWSER_AUTOMATION_ENABLED=false
```

O perfil fica em `runtime/browser_profiles/vibes` e nunca deve ser versionado. Não
grave senhas, cookies ou screenshots fora dos diretórios de runtime. O OpenRouter
continua aceito temporariamente como provider legado para comparação e cutover.

O contrato neutro suporta texto, frame inicial/final, referências aprovadas,
ingredients versionados, duração, proporção, áudio, polling, custo e download. Um
download só é aceito dentro de `storage`, com MIME e assinatura de vídeo válidos.

## Estado operacional

Enquanto não houver um backend browser autorizado, o readiness de vídeo permanece
`degraded` e a submissão falha com mensagem diagnóstica. Isso é intencional: não há
um smoke real honesto sem uma sessão Vibes autorizada e uma automação compatível com
a UI liberada para a conta.
