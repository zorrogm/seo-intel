from seo_intel.urls import looks_like_file, normalize, site_key, start_url


def test_normalize_basics():
    assert normalize("HTTP://Example.COM:80/a/../b/./c?x=1#frag") == "http://example.com/b/c?x=1"
    assert normalize("https://example.com") == "https://example.com/"
    assert normalize("https://example.com:443/a b") == "https://example.com/a%20b"
    assert normalize("https://example.com/%e3%83%84") == "https://example.com/%E3%83%84"
    assert normalize("https://example.com/ツ") == "https://example.com/%E3%83%84"
    assert normalize("https://example.com/a/..") == "https://example.com/"
    assert normalize("https://example.com/a/.") == "https://example.com/a/"


def test_normalize_relative_and_rejects():
    base = "https://example.com/dir/page"
    assert normalize("../x", base) == "https://example.com/x"
    assert normalize("?q=1", base) == "https://example.com/dir/page?q=1"
    assert normalize("//other.com/z", base) == "https://other.com/z"
    assert normalize("mailto:a@b.c", base) is None
    assert normalize("javascript:void(0)", base) is None
    assert normalize("#top", base) == base
    assert normalize("", base) is None
    assert normalize("https://example.com/" + "a" * 3000) is None


def test_site_key_and_files():
    assert site_key("https://www.Example.com/x") == "example.com"
    assert site_key("http://example.com:8080/") == "example.com:8080"
    assert looks_like_file("https://example.com/a/Photo.JPG?x=1")
    assert not looks_like_file("https://example.com/a/page.html")
    assert start_url("example.com") == "https://example.com/"
    assert start_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000/"
