"""Google style robots.txt parser, ported from google/robotstxt."""
from __future__ import annotations

from typing import Dict, Iterator, List, Tuple

from seo_intel.config import ROBOTS_MAX_LINE_BYTES

USER_AGENT = "user-agent"
ALLOW = "allow"
DISALLOW = "disallow"
SITEMAP = "sitemap"
UNKNOWN = "unknown"

_BOM = b"\xef\xbb\xbf"
_HEX = b"0123456789abcdefABCDEF"
_UA_CHARS = frozenset(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_")
_ASCII_SPACE = frozenset(b" \t\n\v\f\r")

# line number, kind, key, value
Directive = Tuple[int, str, bytes, bytes]


def _key_type(key: bytes) -> str:
    k = key.lower()
    if k.startswith((b"user-agent", b"useragent", b"user agent")):
        return USER_AGENT
    if k.startswith(b"allow"):
        return ALLOW
    if k.startswith(
        (b"disallow", b"dissallow", b"dissalow", b"disalow", b"diasllow", b"disallaw")
    ):
        return DISALLOW
    if k.startswith((b"sitemap", b"site-map")):
        return SITEMAP
    return UNKNOWN


def escape_pattern(src: bytes) -> bytes:
    """Escape non-ASCII bytes, uppercase existing escapes."""
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == 0x25 and i + 2 < n and src[i + 1] in _HEX and src[i + 2] in _HEX:
            out += b"%" + src[i + 1 : i + 3].upper()
            i += 3
        elif c & 0x80:
            out += b"%%%02X" % c
            i += 1
        else:
            out.append(c)
            i += 1
    return bytes(out)


def _split_lines(body: bytes) -> Iterator[bytes]:
    """Split lines the way Google does."""
    limit = ROBOTS_MAX_LINE_BYTES - 1
    line = bytearray()
    bom_pos = 0
    last_cr = False
    for ch in body:
        if bom_pos < 3:
            matched = ch == _BOM[bom_pos]
            bom_pos += 1
            if matched:
                continue
            bom_pos = 3
        if ch != 0x0A and ch != 0x0D:
            if len(line) < limit:
                line.append(ch)
        else:
            crlf_continuation = not line and last_cr and ch == 0x0A
            if not crlf_continuation:
                yield bytes(line)
            line = bytearray()
            last_cr = ch == 0x0D
    yield bytes(line)


def _key_value(line: bytes):
    hash_pos = line.find(b"#")
    if hash_pos != -1:
        line = line[:hash_pos]
    line = line.strip()
    if not line:
        return None
    sep = line.find(b":")
    if sep == -1:
        # Google accepts "key value" without a colon
        parts = line.split()
        if len(parts) != 2 or not any(c in b" \t" for c in line):
            return None
        for i, c in enumerate(line):
            if c in b" \t":
                sep = i
                break
        rest = line[sep:].lstrip(b" \t")
        if any(c in b" \t" for c in rest):
            return None
    key = line[:sep].strip()
    if not key:
        return None
    return key, line[sep + 1 :].strip()


def parse(body: bytes) -> Iterator[Directive]:
    """Yield each directive with its line number."""
    for line_num, line in enumerate(_split_lines(body), start=1):
        kv = _key_value(line)
        if kv is None:
            continue
        key, value = kv
        kind = _key_type(key)
        if kind in (ALLOW, DISALLOW, UNKNOWN):
            value = escape_pattern(value)
        yield line_num, kind, key, value


def get_path_params_query(url: str) -> str:
    """Path and query of a URL, no fragment."""
    search_start = 2 if url.startswith("//") else 0

    def first_of(chars: str, start: int) -> int:
        hits = [p for p in (url.find(c, start) for c in chars) if p != -1]
        return min(hits) if hits else -1

    early_path = first_of("/?;", search_start)
    protocol_end = url.find("://", search_start)
    if early_path != -1 and (protocol_end == -1 or early_path < protocol_end):
        protocol_end = -1
    protocol_end = search_start if protocol_end == -1 else protocol_end + 3

    path_start = first_of("/?;", protocol_end)
    if path_start == -1:
        return "/"
    hash_pos = url.find("#", search_start)
    if hash_pos != -1 and hash_pos < path_start:
        return "/"
    path_end = len(url) if hash_pos == -1 else hash_pos
    path = url[path_start:path_end]
    return path if path.startswith("/") else "/" + path


def matches(path: bytes, pattern: bytes) -> bool:
    """Match a path against a robots pattern."""
    anchored = pattern.endswith(b"$")
    if anchored:
        pattern = pattern[:-1]
    if b"*" not in pattern:
        return path == pattern if anchored else path.startswith(pattern)
    parts = pattern.split(b"*")
    if not path.startswith(parts[0]):
        return False
    pos = len(parts[0])
    middle = parts[1:-1] if anchored else parts[1:]
    for part in middle:
        idx = path.find(part, pos)
        if idx == -1:
            return False
        pos = idx + len(part)
    if anchored:
        last = parts[-1]
        return len(path) - len(last) >= pos and path.endswith(last)
    return True


def extract_user_agent(value: bytes) -> bytes:
    end = 0
    while end < len(value) and value[end] in _UA_CHARS:
        end += 1
    return value[:end]


def is_valid_user_agent(agent: str) -> bool:
    raw = agent.encode("utf-8")
    return len(raw) > 0 and extract_user_agent(raw) == raw


class _AgentRules:
    """Rules that apply to one user agent."""

    __slots__ = ("specific", "glob", "ever_seen_specific")

    def __init__(self, directives: List[Directive], agent: bytes):
        self.specific: List[Tuple[bool, bytes]] = []
        self.glob: List[Tuple[bool, bytes]] = []
        self.ever_seen_specific = False
        agent = agent.lower()
        seen_global = seen_specific = seen_separator = False
        for _line, kind, _key, value in directives:
            if kind == USER_AGENT:
                if seen_separator:
                    seen_global = seen_specific = seen_separator = False
                if value[:1] == b"*" and (len(value) == 1 or value[1] in _ASCII_SPACE):
                    seen_global = True
                elif extract_user_agent(value).lower() == agent:
                    seen_specific = self.ever_seen_specific = True
            elif kind in (ALLOW, DISALLOW):
                # Rules outside a group are ignored
                if not (seen_global or seen_specific):
                    continue
                seen_separator = True
                target = self.specific if seen_specific else self.glob
                target.append((kind == ALLOW, value))

    @staticmethod
    def _priorities(rules: List[Tuple[bool, bytes]], path: bytes) -> Tuple[int, int]:
        allow = disallow = -1
        for is_allow, pattern in rules:
            if matches(path, pattern):
                prio = len(pattern)
            elif is_allow:
                # Allowing /dir/index.html also allows /dir/
                slash = pattern.rfind(b"/")
                if slash == -1 or not pattern[slash:].startswith(b"/index.htm"):
                    continue
                alt = pattern[: slash + 1] + b"$"
                if not matches(path, alt):
                    continue
                prio = len(alt)
            else:
                continue
            if is_allow:
                allow = max(allow, prio)
            else:
                disallow = max(disallow, prio)
        return allow, disallow

    def allowed(self, path: bytes) -> bool:
        allow, disallow = self._priorities(self.specific, path)
        if allow > 0 or disallow > 0:
            return not disallow > allow
        if self.ever_seen_specific:
            return True
        allow, disallow = self._priorities(self.glob, path)
        if allow > 0 or disallow > 0:
            return not disallow > allow
        return True


class RobotsTxt:
    """Parse once, then check many URLs."""

    def __init__(self, body: bytes):
        self.directives: List[Directive] = list(parse(body))
        self.sitemaps: List[str] = [
            value.decode("utf-8", "replace")
            for _line, kind, _key, value in self.directives
            if kind == SITEMAP and value
        ]
        self._by_agent: Dict[bytes, _AgentRules] = {}

    def allowed(self, user_agent: str, url: str) -> bool:
        agent = user_agent.encode("utf-8")
        rules = self._by_agent.get(agent)
        if rules is None:
            rules = self._by_agent[agent] = _AgentRules(self.directives, agent)
        path = get_path_params_query(url).encode("utf-8")
        return rules.allowed(path)


def is_allowed(robots_body: bytes, user_agent: str, url: str) -> bool:
    """Parse and check one URL."""
    return RobotsTxt(robots_body).allowed(user_agent, url)
