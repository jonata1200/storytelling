# Configuração e implantação

## CFG-01 — `OPENROUTER_IMAGE_BASE_URL` documentada, mas ignorada

**Severidade:** média  
**Evidência:** `.env.example:33`, `app/providers/image/openrouter.py:29,95`,
`app/config/settings.py:27-51`

O exemplo de ambiente anuncia `OPENROUTER_IMAGE_BASE_URL`, mas `Settings` não declara esse campo
e o provider usa uma constante hardcoded. Como configurações extras são ignoradas, alterar a
variável não produz erro nem efeito.

**Impacto:** proxy, endpoint compatível, ambiente de teste ou futura mudança de URL não funciona,
apesar de a configuração aparentar ser suportada.

## CFG-02 — `OPENROUTER_IMAGE_MODEL` do ambiente também é ignorada

**Severidade:** média  
**Evidência:** `.env.example:32`, `README.md:138`, `app/config/settings.py:25`,
`app/providers/image/openrouter.py:14`

O modelo é uma constante de módulo, não um campo de `Settings`. A variável documentada no `.env`
é descartada. O import dessa constante no provider é inclusive apontado pelo Ruff como não usado.

**Impacto:** operador acredita ter trocado o modelo, mas chamadas continuam usando a política
interna/default persistido.

**Recomendação para CFG-01/02:** ou implementar os campos e testes de precedência, ou remover as
variáveis da documentação e declarar claramente que endpoint/modelo são bloqueados por política.

## CFG-03 — Imagens de containers não estão fixadas por digest

**Severidade:** baixa  
**Evidência:** `docker-compose.yml:2-20`

Postgres usa tag ampla `pg16` e Redis usa `7-alpine`. Recriar o ambiente em datas diferentes pode
baixar binários diferentes, reduzindo reprodutibilidade e introduzindo mudanças sem revisão.

**Recomendação:** fixar versão patch e, para ambientes controlados, digest da imagem.
