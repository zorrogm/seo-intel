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

# Output files, all written deterministically
OUTPUT_FOLDER = "output"
LOG_FOLDER = "logs"
LLM_CACHE_FOLDER = "llm_cache"
FLOAT_DIGITS = 4

# Main content extraction
BLOCK_TAGS = (
    "body", "div", "p", "li", "ul", "ol", "table", "tr", "td", "th", "section",
    "article", "main", "nav", "header", "footer", "aside", "h1", "h2", "h3",
    "h4", "h5", "h6", "blockquote", "pre", "form", "figure", "figcaption",
    "dl", "dt", "dd", "details", "summary", "address",
)
STRIP_TAGS = ("script", "style", "noscript", "template", "svg", "iframe")
CHROME_TAGS = ("nav", "footer", "aside")
TEMPLATE_SAMPLE_PAGES = 500
TEMPLATE_MIN_PAGES = 3
TEMPLATE_MIN_SHARE = 0.10

# Near duplicate detection
SHINGLE_TOKENS = 4
MINHASH_PERMUTATIONS = 64
LSH_BANDS = 16
NEAR_DUPLICATE_OVERLAP = 0.80
LSH_BUCKET_CAP = 50
MIN_TOKENS_FOR_DUPLICATES = 20

# Topic space shared by both sites
VECTOR_DIMENSIONS = 512
MAX_TOKENS_PER_PAGE = 2000
COMMON_TOKEN_SHARE = 0.5
KMEANS_ROUNDS = 15
MAX_TOPICS = 300
TOPIC_LABEL_TERMS = 3

# Cannibalization
CANNIBAL_MIN_SIMILARITY = 0.60
CLUSTER_PAIR_CAP = 400
SEVERITY_WEIGHTS = {
    "content_overlap": 0.30,
    "topic_similarity": 0.30,
    "link_split": 0.20,
    "anchor_conflict": 0.10,
    "depth_closeness": 0.10,
}

# A gap is in depth above these numbers
GAP_MIN_PAGES = 3
GAP_MIN_WORDS = 1500
GAP_MAX_TARGET_SHARE = 0.20

# Intent words, checked in title, heading, URL
INTENT_WORDS = {
    "transactional": (
        "buy", "order", "cart", "checkout", "price", "pricing", "shop", "purchase",
        "book", "subscribe", "download", "coupon", "deal", "discount", "offer",
        "खरीदें", "ऑर्डर", "कीमत", "kharide", "kimat",
    ),
    "commercial": (
        "best", "top", "review", "reviews", "vs", "versus", "compare", "comparison",
        "alternative", "alternatives", "cheapest", "rated",
        "सर्वश्रेष्ठ", "तुलना", "समीक्षा", "sabse",
    ),
    "navigational": (
        "login", "signin", "signup", "register", "account", "contact", "about",
        "careers", "support", "help", "dashboard", "लॉगिन", "संपर्क",
    ),
}
INTENT_MIN_SCORE = 2
DEFAULT_INTENT = "informational"

# Internal link optimiser
PAGERANK_DAMPING = 0.85
PAGERANK_ROUNDS = 100
PAGERANK_TOLERANCE = 1e-10
CONTENT_LINK_WEIGHT = 1.0
NAV_LINK_WEIGHT = 0.0
LINK_BUDGET = 40
MAX_NEW_LINKS_PER_SOURCE = 3
LINK_MIN_RELEVANCE = 0.30
LINK_SOURCES_PER_TARGET = 50
DEFAULT_PRIORITY_COUNT = 10
SENTENCE_MIN_TOKENS = 6
SENTENCE_MAX_TOKENS = 60
ANCHOR_MAX_TOKENS = 4
ANCHOR_MIN_TOKENS = 2

# Action plan
PLAN_ACTIONS = 25

# LLM agent
LLM_MODEL = "gemini-3.5-flash-lite"
LLM_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
LLM_TEMPERATURE = 0.0
LLM_MAX_OUTPUT_TOKENS = 4096
LLM_TIMEOUT_SECONDS = 60.0
LLM_MAX_STEPS = 12
# Leave headroom under the 8,000 token cap
LLM_PROMPT_TOKEN_BUDGET = 6500
LLM_CHARS_PER_TOKEN = 2.5
# Dollars per million tokens, check before submitting
LLM_INPUT_PRICE = 0.10
LLM_OUTPUT_PRICE = 0.40
AGENT_LIST_PAGE_SIZE = 40

# Query parameters that never change the page
NOISE_PARAMS = (
    "gclid", "fbclid", "msclkid", "dclid", "yclid", "mc_cid", "mc_eid", "_ga", "_gl",
    "ref", "ref_src", "igshid",
)
NOISE_PARAM_PREFIXES = ("utm_",)
SESSION_PARAMS = (
    "sid", "sessionid", "session_id", "phpsessid", "jsessionid", "sessid",
    "aspsessionid", "cfid", "cftoken", "zenid", "osCsid",
)

# Spider trap limits
MAX_PATH_DEPTH = 12
MAX_SEGMENT_REPEATS = 3
MAX_QUERY_PARAMS = 4
MAX_QUERY_VARIANTS_PER_PATH = 20
CALENDAR_MAX_PER_SHAPE = 60
CALENDAR_MIN_YEAR = 1995
CALENDAR_FUTURE_YEARS = 2
CALENDAR_PARAMS = ("year", "month", "day", "date", "week", "start", "end", "from", "to")

# Hidden redirects
META_REFRESH_MAX_SECONDS = 10
JS_REDIRECT_MAX_WORDS = 50

# Soft 404 detection
PROBE_SITE_PREFIX = "probe:"
PROBE_PATH_PREFIX = "/seo-intel-missing-page-"
SOFT_404_PROBE_OVERLAP = 0.80
SOFT_404_EMPTY_WORDS = 3
SOFT_404_PHRASE_MAX_WORDS = 150
SOFT_404_PHRASES = (
    "page not found", "not found", "404", "doesn't exist", "does not exist",
    "no longer available", "no longer exists", "cannot be found", "can't be found",
    "nothing found", "no results found", "पृष्ठ नहीं मिला", "नहीं मिला", "उपलब्ध नहीं",
)

# Next day rerun
REVALIDATE_AFTER_HOURS = 12.0
REVALIDATE_SHARE = 0.07

# Link optimiser search effort
GREEDY_SHORTLIST = 8
SWAP_ROUNDS = 1
SWAP_SHORTLIST = 6

# A repeated, link heavy position is chrome
CHROME_PATH_MIN_SHARE = 0.30
CHROME_PATH_LINK_DENSITY = 0.60
PATH_LABEL_LEVELS = 3

# Languages
LANGUAGE_MIN_SHARE = 0.05
DEVANAGARI_MIN_SHARE = 0.5

# LLM help for unclear intent
INTENT_LLM_BATCH = 25
INTENT_LLM_MAX_PAGES = 100
INTENT_CURRENCY_MARKS = ("$", "₹", "€", "£", "rs.", "inr", "usd")
INTENT_CURRENCY_MIN_HITS = 3
INTENTS = ("informational", "commercial", "transactional", "navigational")

# Exact check after the fast vector match
EXACT_TERMS_PER_PAGE = 80
GROUP_MIN_LINK_SHARE = 0.5

# Title, heading and anchor matching channel
HEAD_MIN_SIMILARITY = 0.70
HEAD_TERM_MAX_PAGES = 30
HEAD_MIN_SHARED_TERMS = 2
