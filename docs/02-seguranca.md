# Segurança

## SEC-01 — A UI contorna completamente a autenticação da API

**Severidade:** alta  
**Evidência:** `app/factory.py:19`, `app/factory.py:53-72`,
`app/ui/routes/home_pages.py:143-217`, `app/ui/routes/settings_page.py:34`

O token compartilhado é aplicado apenas ao `private_api_router`. A aplicação, porém, inclui a
NiceGUI por padrão e registra páginas de projetos, ideias e configurações sem dependência de
autenticação ou guarda de sessão. Essas telas chamam serviços internos e podem iniciar operações
pagas ou alterar configurações sem passar pelos endpoints protegidos.

Em um deploy acessível pela rede, `APP_API_TOKEN` protege a API, mas não protege a principal
superfície interativa.

**Impacto:** acesso não autorizado a conteúdo, configurações e geração de IA; potencial consumo
financeiro e alteração/exclusão de dados.

**Recomendação:** exigir autenticação antes de montar/servir a UI em ambientes não locais, ou
desabilitar `include_ui` nesses ambientes e expor a UI somente atrás de um proxy autenticado.

## SEC-02 — Exceções internas são devolvidas ao cliente

**Severidade:** média  
**Evidência:** `app/video_generation/finalization_router.py:57-62`

O endpoint de finalização inclui `str(exc)` na resposta HTTP 500. Erros de FFmpeg, filesystem,
banco ou bibliotecas podem revelar caminhos locais, parâmetros operacionais e detalhes da
infraestrutura.

**Impacto:** vazamento de informação útil para reconhecimento do ambiente e exposição de dados
operacionais nos clientes/logs intermediários.

**Recomendação:** registrar a exceção completa no servidor com correlation ID e retornar ao
cliente apenas uma mensagem genérica e o identificador de diagnóstico.

## SEC-03 — Modo local permite API e UI sem credenciais

**Severidade:** média, dependente da implantação  
**Evidência:** `app/core/auth.py:49-64`, `app/config/settings.py:29-31`

Os defaults são `APP_ENV=local`, debug habilitado e token vazio. Nesse modo a API privada aceita
requisições sem autenticação. Isso é aceitável somente se o servidor estiver rigorosamente preso
ao loopback; uma inicialização em `0.0.0.0`, container ou máquina compartilhada transforma o
default em exposição real.

**Recomendação:** validar também o endereço de bind, emitir alerta de alta visibilidade e recusar
bind não-loopback sem token, mesmo em ambiente local.
