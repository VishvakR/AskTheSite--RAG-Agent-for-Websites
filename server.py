"""AskTheSite HTTP API -- ``uv run uvicorn server:app``."""

from dotenv import load_dotenv

load_dotenv()

from app.api import create_app  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.logger import Logger  # noqa: E402

Logger.setup(get_settings().log_level)

app = create_app()
