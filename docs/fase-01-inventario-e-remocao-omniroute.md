# Fase 01 - Inventario E Remocao Gradual Do OmniRoute

## Objetivo

Mapear todos os pontos em que `omniroute` aparece no codigo, configuracoes,
testes, UI e documentacao, preparando a remocao sem quebrar fluxos existentes.

## Escopo

- Configuracoes em `app/config/settings.py`.
- Politicas em `app/config/provider_policy.py`.
- Preferencias runtime em `app/config/runtime_preferences.py`.
- Providers em `app/providers/**/omniroute.py`.
- Seletores em `app/generation/model_settings.py`.
- Fluxos de imagem/video em `app/visual_bible`, `app/storyboards` e `app/video_generation`.
- Tela de configuracoes em `app/ui/routes/settings_page.py`.
- Testes `tests/test_omniroute_*` e referencias no README.

## Checklist

- [ ] Rodar `rg -n "omniroute|OMNIROUTE|OmniRoute|omnirouter|omniroute" app tests README.md .env.example`.
- [ ] Separar usos de OmniRoute por categoria: texto, imagem, video, speech, docs e testes.
- [ ] Identificar quais tabelas ou registros podem ter `provider="omniroute"` persistido.
- [ ] Criar mapa de compatibilidade para dados antigos.
- [ ] Definir nomes novos de provider: `ollama`, `groq`, `nvidia_nim`, `veo_ai_free`.
- [ ] Planejar migracao de env vars antigas para novas.
- [ ] Remover defaults OmniRoute apenas depois de providers novos passarem nos testes.
- [ ] Manter mensagens de erro antigas enquanto dados legados existirem.

## Mudancas Esperadas

- `SUPPORTED_AI_PROVIDERS` deixara de listar `omniroute`.
- `OMNIROUTE_*` deixara de ser a configuracao padrao.
- Readiness nao devera mais reportar `omniroute` como provider principal.
- README e `.env.example` deverao refletir os novos providers.

## Riscos

- Projetos antigos podem ter `ProjectModelSetting.provider="omniroute"`.
- Jobs antigos podem exibir provider OmniRoute no historico.
- Testes podem depender de mensagens especificas `OMNIROUTE_API_KEY`.

## Criterios De Saida

- [ ] Inventario completo salvo em issue ou nota tecnica.
- [ ] Lista de arquivos afetados revisada.
- [ ] Decisao tomada sobre compatibilidade com dados antigos.
- [ ] Nenhuma remocao destrutiva feita antes da camada nova existir.
