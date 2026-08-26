# Integração Vibes — registro de descoberta

## Estado

Ainda não validada com uma conta de desenvolvimento. Somente API pública documentada ou
automação de navegador expressamente autorizada são opções aceitáveis.

## Capacidade

| Capacidade | Modo pretendido | Estado | Evidência necessária |
| --- | --- | --- | --- |
| Texto para vídeo | API oficial, se disponível | Pendente | Chamada real e documentação oficial |
| Imagem para vídeo | API oficial, se disponível | Pendente | Upload/referência e download validados |
| Ingredients/referências | API oficial, se disponível | Pendente | Identidade estável e reutilização comprovada |
| Geração pela interface | Playwright autorizado, como fallback | Bloqueado por decisão | Confirmação dos termos e autorização da conta |

## Roteiro de validação

Registrar autenticação, limites, duração, 9:16, áudio ligado/desligado, concorrência e rate
limits. Executar texto para vídeo, imagem para vídeo e reutilização de personagem, local e
estilo. Confirmar como uma geração é identificada, como o término é detectado e como o arquivo
original é baixado.

Se a operação for assíncrona, preservar exemplos sanitizados de submit, poll, estados de erro
e download. Não inspecionar nem reproduzir chamadas internas não documentadas do site.

## Credenciais e sessão

- Credenciais ficam no ambiente/secret store local e nunca no Git.
- Um eventual perfil persistente deve ficar em `runtime/browser_profiles/vibes/`.
- O primeiro login pode ser manual; o adapter deve detectar sessão expirada.
- Um lock exclusivo deve impedir dois workers de usar o mesmo perfil.
- Screenshots são apenas diagnósticos locais e não devem conter segredos no repositório.

## Riscos em aberto

- API pública e acesso pela conta ainda não foram confirmados;
- limites, custo, polling e identidade de ingredients são desconhecidos;
- automação depende de autorização e é sensível a mudanças de UI;
- não há fallback operacional escolhido para indisponibilidade do serviço.
