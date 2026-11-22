"""Google's robots_test.cc ported test by test."""
import random

from seo_intel import robots as R
from seo_intel.config import ROBOTS_MAX_LINE_BYTES as MAX_LINE



def ok(robotstxt, agent, url):
    body = robotstxt if isinstance(robotstxt, bytes) else robotstxt.encode("utf-8")
    return R.is_allowed(body, agent, url)


def stats(body):
    """Count valid, unknown, last line, sitemap."""
    valid = unknown = last = 0
    sitemap = ""
    for line, kind, _key, value in R.parse(body):
        assert line >= last
        last = line
        if kind == R.UNKNOWN:
            unknown += 1
        else:
            valid += 1
            if kind == R.SITEMAP:
                sitemap += value.decode()
    return valid, unknown, last, sitemap


def test_GoogleOnly_SystemTest():
    robotstxt = "user-agent: FooBot\ndisallow: /\n"
    assert ok("", "FooBot", "")
    assert ok(robotstxt, "", "")
    assert not ok(robotstxt, "FooBot", "")
    assert ok("", "", "")


def test_ID_LineSyntax_Line():
    url = "http://foo.bar/x/y"
    assert not ok("user-agent: FooBot\ndisallow: /\n", "FooBot", url)
    assert ok("foo: FooBot\nbar: /\n", "FooBot", url)
    assert not ok("user-agent FooBot\ndisallow /\n", "FooBot", url)


def test_ID_LineSyntax_Groups():
    robotstxt = (
        "allow: /foo/bar/\n"
        "\n"
        "user-agent: FooBot\n"
        "disallow: /\n"
        "allow: /x/\n"
        "user-agent: BarBot\n"
        "disallow: /\n"
        "allow: /y/\n"
        "\n"
        "\n"
        "allow: /w/\n"
        "user-agent: BazBot\n"
        "\n"
        "user-agent: FooBot\n"
        "allow: /z/\n"
        "disallow: /\n"
    )
    url_w = "http://foo.bar/w/a"
    url_x = "http://foo.bar/x/b"
    url_y = "http://foo.bar/y/c"
    url_z = "http://foo.bar/z/d"
    url_foo = "http://foo.bar/foo/bar/"

    assert ok(robotstxt, "FooBot", url_x)
    assert ok(robotstxt, "FooBot", url_z)
    assert not ok(robotstxt, "FooBot", url_y)
    assert ok(robotstxt, "BarBot", url_y)
    assert ok(robotstxt, "BarBot", url_w)
    assert not ok(robotstxt, "BarBot", url_z)
    assert ok(robotstxt, "BazBot", url_z)

    # Rules outside groups are ignored
    assert not ok(robotstxt, "FooBot", url_foo)
    assert not ok(robotstxt, "BarBot", url_foo)
    assert not ok(robotstxt, "BazBot", url_foo)


def test_ID_LineSyntax_Groups_OtherRules():
    url = "http://foo.bar/"
    robotstxt = (
        "User-agent: BarBot\n"
        "Sitemap: https://foo.bar/sitemap\n"
        "User-agent: *\n"
        "Disallow: /\n"
    )
    assert not ok(robotstxt, "FooBot", url)
    assert not ok(robotstxt, "BarBot", url)
    robotstxt = (
        "User-agent: FooBot\n"
        "Invalid-Unknown-Line: unknown\n"
        "User-agent: *\n"
        "Disallow: /\n"
    )
    assert not ok(robotstxt, "FooBot", url)
    assert not ok(robotstxt, "BarBot", url)


def test_ID_REPLineNamesCaseInsensitive():
    upper = "USER-AGENT: FooBot\nALLOW: /x/\nDISALLOW: /\n"
    lower = "user-agent: FooBot\nallow: /x/\ndisallow: /\n"
    camel = "uSeR-aGeNt: FooBot\nAlLoW: /x/\ndIsAlLoW: /\n"
    for robotstxt in (upper, lower, camel):
        assert ok(robotstxt, "FooBot", "http://foo.bar/x/y")
        assert not ok(robotstxt, "FooBot", "http://foo.bar/a/b")


def test_ID_VerifyValidUserAgentsToObey():
    assert R.is_valid_user_agent("Foobot")
    assert R.is_valid_user_agent("Foobot-Bar")
    assert R.is_valid_user_agent("Foo_Bar")

    assert not R.is_valid_user_agent("")
    assert not R.is_valid_user_agent("ツ")

    assert not R.is_valid_user_agent("Foobot*")
    assert not R.is_valid_user_agent(" Foobot ")
    assert not R.is_valid_user_agent("Foobot/2.1")

    assert not R.is_valid_user_agent("Foobot Bar")


def test_ID_UserAgentValueCaseInsensitive():
    upper = "User-Agent: FOO BAR\nAllow: /x/\nDisallow: /\n"
    lower = "User-Agent: foo bar\nAllow: /x/\nDisallow: /\n"
    camel = "User-Agent: FoO bAr\nAllow: /x/\nDisallow: /\n"
    for agent in ("Foo", "foo"):
        for robotstxt in (upper, lower, camel):
            assert ok(robotstxt, agent, "http://foo.bar/x/y")
            assert not ok(robotstxt, agent, "http://foo.bar/a/b")


def test_GoogleOnly_AcceptUserAgentUpToFirstSpace():
    assert not R.is_valid_user_agent("Foobot Bar")
    robotstxt = (
        "User-Agent: *\n"
        "Disallow: /\n"
        "User-Agent: Foo Bar\n"
        "Allow: /x/\n"
        "Disallow: /\n"
    )
    url = "http://foo.bar/x/y"
    assert ok(robotstxt, "Foo", url)
    assert not ok(robotstxt, "Foo Bar", url)


def test_ID_GlobalGroups_Secondary():
    robotstxt_global = (
        "user-agent: *\n"
        "allow: /\n"
        "user-agent: FooBot\n"
        "disallow: /\n"
    )
    robotstxt_only_specific = (
        "user-agent: FooBot\n"
        "allow: /\n"
        "user-agent: BarBot\n"
        "disallow: /\n"
        "user-agent: BazBot\n"
        "disallow: /\n"
    )
    url = "http://foo.bar/x/y"
    assert ok("", "FooBot", url)
    assert not ok(robotstxt_global, "FooBot", url)
    assert ok(robotstxt_global, "BarBot", url)
    assert ok(robotstxt_only_specific, "QuxBot", url)


def test_ID_AllowDisallow_Value_CaseSensitive():
    url = "http://foo.bar/x/y"
    assert not ok("user-agent: FooBot\ndisallow: /x/\n", "FooBot", url)
    assert ok("user-agent: FooBot\ndisallow: /X/\n", "FooBot", url)


def test_ID_LongestMatch():
    url = "http://foo.bar/x/page.html"

    robotstxt = "user-agent: FooBot\ndisallow: /x/page.html\nallow: /x/\n"
    assert not ok(robotstxt, "FooBot", url)

    robotstxt = "user-agent: FooBot\nallow: /x/page.html\ndisallow: /x/\n"
    assert ok(robotstxt, "FooBot", url)
    assert not ok(robotstxt, "FooBot", "http://foo.bar/x/")

    # Same length allow and disallow: allow wins
    robotstxt = "user-agent: FooBot\ndisallow: \nallow: \n"
    assert ok(robotstxt, "FooBot", url)

    robotstxt = "user-agent: FooBot\ndisallow: /\nallow: /\n"
    assert ok(robotstxt, "FooBot", url)

    robotstxt = "user-agent: FooBot\ndisallow: /x\nallow: /x/\n"
    assert not ok(robotstxt, "FooBot", "http://foo.bar/x")
    assert ok(robotstxt, "FooBot", "http://foo.bar/x/")

    robotstxt = "user-agent: FooBot\ndisallow: /x/page.html\nallow: /x/page.html\n"
    assert ok(robotstxt, "FooBot", url)

    # Longest match wins.
    robotstxt = "user-agent: FooBot\nallow: /page\ndisallow: /*.html\n"
    assert not ok(robotstxt, "FooBot", "http://foo.bar/page.html")
    assert ok(robotstxt, "FooBot", "http://foo.bar/page")

    robotstxt = "user-agent: FooBot\nallow: /x/page.\ndisallow: /*.html\n"
    assert ok(robotstxt, "FooBot", url)
    assert not ok(robotstxt, "FooBot", "http://foo.bar/x/y.html")

    # FooBot group wins, so /x/ is allowed
    robotstxt = (
        "User-agent: *\n"
        "Disallow: /x/\n"
        "User-agent: FooBot\n"
        "Disallow: /y/\n"
    )
    assert ok(robotstxt, "FooBot", "http://foo.bar/x/page")
    assert not ok(robotstxt, "FooBot", "http://foo.bar/y/page")


def test_ID_Encoding():
    # Query strings stay unencoded
    robotstxt = (
        "User-agent: FooBot\n"
        "Disallow: /\n"
        "Allow: /foo/bar?qux=taz&baz=http://foo.bar?tar&par\n"
    )
    assert ok(robotstxt, "FooBot", "http://foo.bar/foo/bar?qux=taz&baz=http://foo.bar?tar&par")

    # A 3 byte character gets percent encoded
    robotstxt = "User-agent: FooBot\nDisallow: /\nAllow: /foo/bar/ツ\n"
    assert ok(robotstxt, "FooBot", "http://foo.bar/foo/bar/%E3%83%84")
    # Pattern gets encoded, the raw URL does not
    assert not ok(robotstxt, "FooBot", "http://foo.bar/foo/bar/ツ")

    # Already encoded characters stay as they are
    robotstxt = "User-agent: FooBot\nDisallow: /\nAllow: /foo/bar/%E3%83%84\n"
    assert ok(robotstxt, "FooBot", "http://foo.bar/foo/bar/%E3%83%84")
    assert not ok(robotstxt, "FooBot", "http://foo.bar/foo/bar/ツ")

    # Encoded plain ASCII only matches literally
    robotstxt = "User-agent: FooBot\nDisallow: /\nAllow: /foo/bar/%62%61%7A\n"
    assert not ok(robotstxt, "FooBot", "http://foo.bar/foo/bar/baz")
    assert ok(robotstxt, "FooBot", "http://foo.bar/foo/bar/%62%61%7A")


def test_ID_SpecialCharacters():
    robotstxt = "User-agent: FooBot\nDisallow: /foo/bar/quz\nAllow: /foo/*/qux\n"
    assert not ok(robotstxt, "FooBot", "http://foo.bar/foo/bar/quz")
    assert ok(robotstxt, "FooBot", "http://foo.bar/foo/quz")
    assert ok(robotstxt, "FooBot", "http://foo.bar/foo//quz")
    assert ok(robotstxt, "FooBot", "http://foo.bar/foo/bax/quz")

    robotstxt = "User-agent: FooBot\nDisallow: /foo/bar$\nAllow: /foo/bar/qux\n"
    assert not ok(robotstxt, "FooBot", "http://foo.bar/foo/bar")
    assert ok(robotstxt, "FooBot", "http://foo.bar/foo/bar/qux")
    assert ok(robotstxt, "FooBot", "http://foo.bar/foo/bar/")
    assert ok(robotstxt, "FooBot", "http://foo.bar/foo/bar/baz")

    robotstxt = (
        "User-agent: FooBot\n"
        "# Disallow: /\n"
        "Disallow: /foo/quz#qux\n"
        "Allow: /\n"
    )
    assert ok(robotstxt, "FooBot", "http://foo.bar/foo/bar")
    assert not ok(robotstxt, "FooBot", "http://foo.bar/foo/quz")


def test_GoogleOnly_IndexHTMLisDirectory():
    robotstxt = (
        "User-Agent: *\n"
        "Allow: /allowed-slash/index.html\n"
        "Disallow: /\n"
    )
    # Allowing index.html allows the folder too
    assert ok(robotstxt, "foobot", "http://foo.com/allowed-slash/")
    # Does not exactly match.
    assert not ok(robotstxt, "foobot", "http://foo.com/allowed-slash/index.htm")
    # Exact match.
    assert ok(robotstxt, "foobot", "http://foo.com/allowed-slash/index.html")
    assert not ok(robotstxt, "foobot", "http://foo.com/anyother-url")


def test_GoogleOnly_LineTooLong():
    eol_len = 1
    allow = "allow: "
    disallow = "disallow: "

    # Long disallow line is cut, still matches
    robotstxt = "user-agent: FooBot\n"
    longline = "/x/"
    max_length = MAX_LINE - len(longline) - len(disallow) + eol_len
    longline += "a" * (max_length - len(longline))
    robotstxt += disallow + longline + "/qux\n"

    # Matches nothing, so URL is allowed.
    assert ok(robotstxt, "FooBot", "http://foo.bar/fux")
    # Matches cut off disallow rule.
    assert not ok(robotstxt, "FooBot", "http://foo.bar" + longline + "/fux")

    robotstxt = "user-agent: FooBot\ndisallow: /\n"
    longline_a = "/x/"
    longline_b = "/x/"
    max_length = MAX_LINE - len(longline_a) - len(allow) + eol_len
    pad = max_length - len(longline_a)
    longline_a += "a" * pad
    longline_b += "b" * pad
    robotstxt += allow + longline_a + "/qux\n"
    robotstxt += allow + longline_b + "/qux\n"

    # URL matches the disallow rule.
    assert not ok(robotstxt, "FooBot", "http://foo.bar/")
    # Matches the allow rule exactly.
    assert ok(robotstxt, "FooBot", "http://foo.bar" + longline_a + "/qux")
    # Matches cut off allow rule.
    assert ok(robotstxt, "FooBot", "http://foo.bar" + longline_b + "/fux")


def test_GoogleOnly_DocumentationChecks():
    def check(robotstxt, allowed, disallowed):
        for path in allowed:
            assert ok(robotstxt, "FooBot", "http://foo.bar" + path), path
        for path in disallowed:
            assert not ok(robotstxt, "FooBot", "http://foo.bar" + path), path

    check(
        "user-agent: FooBot\ndisallow: /\nallow: /fish\n",
        ["/fish", "/fish.html", "/fish/salmon.html", "/fishheads",
         "/fishheads/yummy.html", "/fish.html?id=anything"],
        ["/bar", "/Fish.asp", "/catfish", "/?id=fish"],
    )
    # "/fish*" equals "/fish"
    check(
        "user-agent: FooBot\ndisallow: /\nallow: /fish*\n",
        ["/fish", "/fish.html", "/fish/salmon.html", "/fishheads",
         "/fishheads/yummy.html", "/fish.html?id=anything"],
        ["/bar", "/Fish.bar", "/catfish", "/?id=fish"],
    )
    # "/fish/" does not equal "/fish"
    check(
        "user-agent: FooBot\ndisallow: /\nallow: /fish/\n",
        ["/fish/", "/fish/salmon", "/fish/?salmon", "/fish/salmon.html",
         "/fish/?id=anything"],
        ["/bar", "/fish", "/fish.html", "/Fish/Salmon.html"],
    )
    # "/*.php"
    check(
        "user-agent: FooBot\ndisallow: /\nallow: /*.php\n",
        ["/filename.php", "/folder/filename.php", "/folder/filename.php?parameters",
         "//folder/any.php.file.html", "/filename.php/", "/index?f=filename.php/"],
        ["/bar", "/php/", "/index?php", "/windows.PHP"],
    )
    # "/*.php$"
    check(
        "user-agent: FooBot\ndisallow: /\nallow: /*.php$\n",
        ["/filename.php", "/folder/filename.php"],
        ["/bar", "/filename.php?parameters", "/filename.php/", "/filename.php5",
         "/php/", "/filename?php", "/aaaphpaaa", "//windows.PHP"],
    )
    # "/fish*.php"
    check(
        "user-agent: FooBot\ndisallow: /\nallow: /fish*.php\n",
        ["/fish.php", "/fishheads/catfish.php?parameters"],
        ["/bar", "/Fish.PHP"],
    )

    # Order of precedence examples from Google docs
    assert ok("user-agent: FooBot\nallow: /p\ndisallow: /\n", "FooBot",
              "http://example.com/page")
    assert ok("user-agent: FooBot\nallow: /folder\ndisallow: /folder\n", "FooBot",
              "http://example.com/folder/page")
    assert not ok("user-agent: FooBot\nallow: /page\ndisallow: /*.htm\n", "FooBot",
                  "http://example.com/page.htm")
    robotstxt = "user-agent: FooBot\nallow: /$\ndisallow: /\n"
    assert ok(robotstxt, "FooBot", "http://example.com/")
    assert not ok(robotstxt, "FooBot", "http://example.com/page.html")


def test_ID_LinesNumbersAreCountedCorrectly():
    unix = b"User-Agent: foo\nAllow: /some/path\nUser-Agent: bar\n\n\nDisallow: /\n"
    dos = b"User-Agent: foo\r\nAllow: /some/path\r\nUser-Agent: bar\r\n\r\n\r\nDisallow: /\r\n"
    mac = b"User-Agent: foo\rAllow: /some/path\rUser-Agent: bar\r\r\rDisallow: /\r"
    no_final_newline = b"User-Agent: foo\nAllow: /some/path\nUser-Agent: bar\n\n\nDisallow: /"
    mixed = b"User-Agent: foo\nAllow: /some/path\r\nUser-Agent: bar\n\r\n\nDisallow: /"
    for body in (unix, dos, mac, no_final_newline, mixed):
        valid, _unknown, last, _sitemap = stats(body)
        assert valid == 4
        assert last == 6


def test_ID_UTF8ByteOrderMarkIsSkipped():
    rest = b"User-Agent: foo\nAllow: /AnyValue\n"
    # Full and partial BOMs are skipped
    for bom in (b"\xEF\xBB\xBF", b"\xEF\xBB", b"\xEF"):
        valid, unknown, _last, _sitemap = stats(bom + rest)
        assert (valid, unknown) == (2, 0)

    # A broken BOM spoils the first line
    valid, unknown, _last, _sitemap = stats(b"\xEF\x11\xBF" + rest)
    assert (valid, unknown) == (1, 1)

    # A BOM mid file is not skipped
    valid, unknown, _last, _sitemap = stats(
        b"User-Agent: foo\n\xEF\xBB\xBFAllow: /AnyValue\n"
    )
    assert (valid, unknown) == (1, 1)


def test_ID_NonStandardLineExample_Sitemap():
    sitemap_loc = "http://foo.bar/sitemap.xml"
    groups = "User-Agent: foo\nAllow: /some/path\nUser-Agent: bar\n\n\n"

    body = (groups + "Sitemap: " + sitemap_loc + "\n").encode()
    assert stats(body)[3] == sitemap_loc
    # Sitemap lines can appear anywhere
    body = ("Sitemap: " + sitemap_loc + "\n" + groups).encode()
    assert stats(body)[3] == sitemap_loc
    assert R.RobotsTxt(body).sitemaps == [sitemap_loc]


def test_TestGetPathParamsQuery():
    cases = [
        ("", "/"),
        ("http://www.example.com", "/"),
        ("http://www.example.com/", "/"),
        ("http://www.example.com/a", "/a"),
        ("http://www.example.com/a/", "/a/"),
        ("http://www.example.com/a/b?c=http://d.e/", "/a/b?c=http://d.e/"),
        ("http://www.example.com/a/b?c=d&e=f#fragment", "/a/b?c=d&e=f"),
        ("example.com", "/"),
        ("example.com/", "/"),
        ("example.com/a", "/a"),
        ("example.com/a/", "/a/"),
        ("example.com/a/b?c=d&e=f#fragment", "/a/b?c=d&e=f"),
        ("a", "/"),
        ("a/", "/"),
        ("/a", "/a"),
        ("a/b", "/b"),
        ("example.com?a", "/?a"),
        ("example.com/a;b#c", "/a;b"),
        ("//a/b/c", "/b/c"),
    ]
    for url, expected in cases:
        assert R.get_path_params_query(url) == expected, url


def test_TestMaybeEscapePattern():
    assert R.escape_pattern(b"http://www.example.com") == b"http://www.example.com"
    assert R.escape_pattern(b"/a/b/c") == b"/a/b/c"
    assert R.escape_pattern("á".encode()) == b"%C3%A1"
    assert R.escape_pattern(b"%aa") == b"%AA"


# Extra check: fast matcher equals Google's algorithm


def _google_matches(path, pattern):
    """Google's original matching loop, copied line by line."""
    pathlen = len(path)
    pos = [0]
    for i, pat in enumerate(pattern):
        # A dollar sign at the very end
        if pat == 0x24 and i + 1 == len(pattern):
            return pos[-1] == pathlen
        if pat == 0x2A:
            pos = list(range(pos[0], pathlen + 1))
        else:
            pos = [p + 1 for p in pos if p < pathlen and path[p] == pat]
            if not pos:
                return False
    return True


def test_fast_matcher_agrees_with_google_algorithm():
    rng = random.Random(7)
    alphabet = b"ab/*$"
    for _ in range(40000):
        path = b"/" + bytes(rng.choice(b"ab/$") for _ in range(rng.randint(0, 8)))
        pattern = bytes(rng.choice(alphabet) for _ in range(rng.randint(0, 7)))
        assert R.matches(path, pattern) == _google_matches(path, pattern), (path, pattern)
