import argparse
import logging

import uvicorn

from app.config.settings import DEFAULT_APP_SECRET_KEY, get_settings
from app.core.auth import configured_api_token
from app.runtime import configure_windows_event_loop_policy

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Storytelling server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    non_local = settings.app_env.lower() not in {"local", "development", "test"}
    if args.reload and non_local:
        raise SystemExit(
            f"--reload nao e permitido em APP_ENV={settings.app_env}. "
            "Use --reload apenas em desenvolvimento local."
        )
    if args.host not in {"127.0.0.1", "localhost"}:
        if configured_api_token() is None:
            raise SystemExit(
                "Binding de rede exige APP_API_TOKEN. Configure um token ou use 127.0.0.1."
            )
        if settings.app_secret_key == DEFAULT_APP_SECRET_KEY:
            logger.warning(
                "Binding em %s com APP_SECRET_KEY default: qualquer cliente na rede "
                "pode forjar tokens de sessao. Defina um segredo proprio.",
                args.host,
            )
        if non_local:
            logger.warning(
                "Binding em %s em ambiente nao-local: certifique-se de que ha "
                "autenticacao (APP_API_TOKEN) e proxy reverso adequado.",
                args.host,
            )

    configure_windows_event_loop_policy()
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        loop="asyncio",
    )


if __name__ == "__main__":
    main()
