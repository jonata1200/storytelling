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

- [ ] Criar `scripts/story.ps1`.
- [ ] Implementar comando `run`.
- [ ] Implementar comando `stop`.
- [ ] Implementar comando `restart`.
- [ ] Preservar opcoes `-Dev`, `-Background`, `-NoDocker`, `-NoMigrate` e `-KeepDocker`.
- [ ] Mover comandos menos usados para `tools`: `status`, `logs`, `check`, `test`, `clean` e `migrate`.
- [ ] Transformar `scripts/app.ps1` em wrapper temporario para `story.ps1`.
- [ ] Transformar `scripts/executar.ps1` em wrapper para `story.ps1 run`.
- [ ] Transformar `scripts/finalizar.ps1` em wrapper para `story.ps1 stop`.
- [ ] Atualizar o README para documentar somente `run`, `stop` e `restart` como comandos principais.
- [ ] Testar `.\scripts\story.ps1 run`.
- [ ] Testar `.\scripts\story.ps1 stop`.
- [ ] Testar `.\scripts\story.ps1 restart`.
- [ ] Testar `.\scripts\story.ps1 tools status`.
- [ ] Testar `.\scripts\story.ps1 tools logs`.

## Criterios de Aceite

- A aplicacao sobe com um unico comando.
- A aplicacao para com um unico comando.
- O restart funciona sem deixar processo antigo preso na porta.
- Os comandos antigos ainda funcionam durante a janela de compatibilidade.
