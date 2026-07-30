# Guia De Reconexao Veo AI Free

1. Abra o Veo AI Free manualmente no navegador.
2. Confirme que a sessao esta autenticada ou ativa.
3. Exporte ou copie os cookies relevantes como JSON.
4. Na tela de Configuracoes de IA, cole o bundle em `Bundle JSON de cookies Veo AI Free`.
5. Salve a sessao e confira o readiness `veo_ai_free_session`.

Formato aceito:

```json
{
  "cookies": [
    {
      "name": "session",
      "value": "valor-do-cookie",
      "domain": "dominio-do-site",
      "expires": 1893456000
    }
  ],
  "user_agent": "Mozilla/5.0"
}
```

Tambem sao aceitos exports com `expirationDate`; a aplicacao converte para
`expires`.

Nao cole tokens em issues, logs, README ou mensagens de erro.
