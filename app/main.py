from app.factory import create_app
from app.runtime import configure_windows_event_loop_policy

configure_windows_event_loop_policy()

app = create_app()
