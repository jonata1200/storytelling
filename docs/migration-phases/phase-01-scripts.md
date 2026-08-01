# Fase 01 - Scripts Locais Simplificados

## Objetivo

Unificar a operacao local em apenas 3 comandos de uso diario:

```powershell
.\scripts\story.ps1 run
.\scripts\story.ps1 stop
.\scripts\story.ps1 restart
```

## Resultado Esperado

- `run`: sobe Docker, aguarda banco, aplica migrations e inicia a aplicacao.
- `stop`: finaliza aplicacao e containers.
- `restart`: executa `stop` e depois `run`.
- Comandos tecnicos continuam disponiveis em `tools`.

## Checklist

- [x] Criar `scripts/story.ps1`.
- [x] Implementar comando `run`.
- [x] Implementar comando `stop`.
- [x] Implementar comando `restart`.
- [x] Preservar opcoes `-Dev`, `-Background`, `-NoDocker`, `-NoMigrate` e `-KeepDocker`.
- [x] Mover comandos menos usados para `tools`: `status`, `logs`, `check`, `test`, `clean` e `migrate`.
- [x] Transformar `scripts/app.ps1` em wrapper temporario para `story.ps1`.
- [x] Transformar `scripts/executar.ps1` em wrapper para `story.ps1 run`.
- [x] Transformar `scripts/finalizar.ps1` em wrapper para `story.ps1 stop`.
- [x] Atualizar o README para documentar somente `run`, `stop` e `restart` como comandos principais.
- [x] Testar `.\scripts\story.ps1 run`.
- [x] Testar `.\scripts\story.ps1 stop`.
- [ ] Testar `.\scripts\story.ps1 restart` em ambiente local completo.
- [x] Testar `.\scripts\story.ps1 tools status`.
- [x] Testar `.\scripts\story.ps1 tools logs`.

## Criterios de Aceite

- A aplicacao sobe com um unico comando.
- A aplicacao para com um unico comando.
- O restart funciona sem deixar processo antigo preso na porta.
- Os comandos antigos ainda funcionam durante a janela de compatibilidade.

## Status de Validacao

- `tools status`, `tools logs`, `app.ps1 status`, `executar.ps1` e `finalizar.ps1`
  foram validados localmente.
- `restart` ficou pendente para validacao manual em ambiente local completo.
