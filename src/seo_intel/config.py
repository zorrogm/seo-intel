"""All settings and limits live here, nowhere else."""
from __future__ import annotations

# Name we send and match in robots.txt
USER_AGENT_TOKEN = "SeoIntelBot"
USER_AGENT = "Mozilla/5.0 (compatible; SeoIntelBot/0.1)"

# Hard limits from the assessment brief
MAX_URLS_PER_SITE = 50_000
MAX_REQUESTS_PER_SECOND = 3.0
MAX_RUN_MINUTES = 90
MAX_RAM_GB = 2.0
MAX_LLM_COST_USD = 0.50
MAX_RENDER_SHARE = 0.15
MAX_TRAP_BUDGET_SHARE = 0.05
MAX_LLM_PAGE_SHARE = 0.02
MAX_LLM_INPUT_TOKENS = 8_000

# Same numbers Google's robots parser uses
ROBOTS_MAX_LINE_BYTES = 2083 * 8
ROBOTS_MAX_FILE_BYTES = 500 * 1024
ROBOTS_MAX_REDIRECTS = 5

# Every run writes under this folder
OUTPUT_DIR_NAME = "runs"
DEFAULT_SEED = 0

# LLM key is read from this variable
LLM_API_KEY_ENV = "GEMINI_API_KEY"
ENV_FILE_NAME = ".env"

# Crawl gets this share of the run
CRAWL_MINUTES = 60.0
# Gap keeps us safely under 3 per second
REQUEST_GAP_SECONDS = 0.34
WORKERS_PER_SITE = 4
CONNECT_TIMEOUT_SECONDS = 10.0
READ_TIMEOUT_SECONDS = 20.0
FETCH_RETRIES = 2
MAX_RETRY_WAIT_SECONDS = 30.0
MAX_BODY_BYTES = 3 * 1024 * 1024
MAX_URL_LENGTH = 2083
MAX_SITEMAP_FILES = 50
HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
CRAWL_DB_NAME = "crawl.sqlite"
PROGRESS_SECONDS = 10.0

# Links to these file types are never fetched
SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".avif",
    ".css", ".js", ".mjs", ".json", ".xml", ".rss", ".atom", ".txt",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv",
    ".zip", ".gz", ".rar", ".7z", ".tar", ".dmg", ".exe", ".apk",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".webm", ".wav", ".ogg",
    ".woff", ".woff2", ".ttf", ".eot",
)
SITEMAP_MAX_BYTES = 20 * 1024 * 1024
START_MAX_REDIRECTS = 5
FRONTIER_BATCH = 8
IDLE_POLL_SECONDS = 0.05
