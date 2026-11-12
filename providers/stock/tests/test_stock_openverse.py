"""stock:media on Openverse (providers/stock/openverse.py): the per-item licence table, the host list, no key, and a committed source file of nulls.
Every id, name and host is made up; the network is the kit's fake."""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import pytest
import stock_kit as kit
from stock_kit import API, IMG, Run, image_response, json_response, source

import _stock
import openverse

COMMITTED = Path(openverse.__file__).resolve().parent / "sources" / "openverse.json"
TABLE = {"by 4.0": "cc-by-4.0", "by 3.0": "cc-by-3.0", "by 2.5": "cc-by-2.5", "by 2.0": "cc-by-2.0", "cc0 1.0": "cc0-1.0", "pdm 1.0": "pdm-1.0"}
COMMITTED_TODAY = "2026-11-11"        # the day the committed file's terms were read (kit.TODAY is earlier)
SEARCH, ITEM = "/v2/pictures/", "/v2/pictures/{item}/"


def uid(n):
    return "aa000000-0000-4000-8000-%012d" % n


def data(**over):
    base = dict(source="openverse", licence_tier="per-item", licence=None, licences=dict(TABLE), secret=None, secret_in="none",
                credit_line="credit line", kinds=["image"],
                api={"host": API, "search_image": SEARCH, "search_clip": None, "item_image": ITEM, "item_clip": None},
                path_patterns={"preview": r"/t/[0-9a-f-]+\.jpg", "image": r"/f/[0-9a-f-]+\.jpg", "clip": None},
                rendition={"preview": "thumb", "image": "full", "clip": None})
    base.update(over)
    return source(**base)


def item(n=1, licence="by", version="4.0", author="Aster Lane", host=IMG, thumb_host=IMG, width=2400, height=3200):
    return {"id": uid(n), "title": "Quiet harbour", "creator": author, "license": licence, "license_version": version, "width": width, "height": height,
            "foreign_landing_url": "https://page.stock.example/photo/%d" % n, "thumbnail": "https://%s/t/%s.jpg" % (thumb_host, uid(n)),
            "url": "https://%s/f/%s.jpg" % (host, uid(n))}


def make(tmp_path, monkeypatch, **over):
    return Run(tmp_path, monkeypatch, data(**over), impl=openverse, resolver=kit.FakeResolver({"STOCK_PEXELS_API_KEY": kit.KEY}))


def fresh(tmp_path, name):
    """A new folder of its own, for a test that makes several runs."""
    path = tmp_path / name
    path.mkdir()
    return path


def serve(r, items):
    r.net.add(API, SEARCH, json_response({"results": items}))
    for i in items:
        r.net.add(IMG, "/t/%s.jpg" % i["id"], image_response())
        r.net.add(IMG, "/f/%s.jpg" % i["id"], image_response())
    return r


# --- the class sees it ---------------------------------------------------------------------------------------------------------------

def test_the_implementation_declares_the_class_and_its_verbs():
    assert (openverse.SERVES, openverse.SOURCE, openverse.VERBS) == ("stock:media", "openverse", ("search", "fetch"))
    assert openverse.SECRET == ""                       # no key exists, so none is named: a source file that names one is refused (below)


def test_the_committed_source_file_holds_the_approved_values_and_is_ready(tmp_path, monkeypatch):
    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))
    assert list(committed) == list(_stock.SOURCE_KEYS)
    assert (committed["source"], committed["licence_tier"], committed["secret_in"], committed["kinds"]) == ("openverse", "per-item", "none", ["image"])
    assert committed["licence"] is None and committed["secret"] is None
    assert committed["licences"] == {"cc0 1.0": "cc0-1.0", "pdm 1.0": "pdm-1.0", "by 4.0": "cc-by-4.0", "by 3.0": "cc-by-3.0", "by 2.5": "cc-by-2.5",
                                     "by 2.0": "cc-by-2.0"}
    assert committed["licence_url"] == "https://docs.openverse.org/terms_of_service.html" and committed["terms_read_on"] == "2026-11-11"
    assert committed["api"] == {"host": "api.openverse.org", "search_image": "/v1/images/", "search_clip": None, "item_image": "/v1/images/{item}/", "item_clip": None}
    assert committed["media_hosts"] == ["api.openverse.org", "live.staticflickr.com", "upload.wikimedia.org"] and committed["redirect_hosts"] == []
    assert committed["path_patterns"]["preview"] == "^/v1/images/[0-9a-f-]{36}/thumb/$" and committed["path_patterns"]["clip"] is None
    assert committed["rendition"] == {"preview": "thumbnail", "image": "url", "clip": None}
    assert committed["cache_seconds"] == 86400 and committed["credit_line"] == "{title} by {author}, {licence}, via Openverse"
    ready = _stock.read_source(str(COMMITTED), COMMITTED_TODAY, "openverse", None)       # no refusal: the file is ready
    assert set(ready["_patterns"]) == {"preview", "image"}
    r = make(tmp_path, monkeypatch)
    monkeypatch.setitem(_stock.SEAMS, "sources", None)               # the real rule: providers/stock/sources/openverse.json
    code, got = r.run("--check", source_file=str(COMMITTED), today=COMMITTED_TODAY)
    assert code == 0 and got["ok"] is True and got["source"] == "openverse"
    assert r.net.count() == 0


def test_the_committed_licence_table_maps_the_four_keys_and_drops_the_rest():
    table = json.loads(COMMITTED.read_text(encoding="utf-8"))["licences"]
    for licence, version, expected in (("cc0", "1.0", "cc0-1.0"), ("pdm", "1.0", "pdm-1.0"), ("by", "4.0", "cc-by-4.0"), ("by", "3.0", "cc-by-3.0"),
                                  ("by", "2.5", "cc-by-2.5"), ("by", "2.0", "cc-by-2.0")):
        assert _stock.map_licence(table, openverse.licence_key({"license": licence, "license_version": version})) == expected
    for licence, version in (("by-sa", "4.0"), ("by-nc", "4.0"), ("by-nd", "4.0"), ("by", None), ("by", "1.0"), ("by-sa", "2.0")):
        assert _stock.map_licence(table, openverse.licence_key({"license": licence, "license_version": version})) is None


def test_check_needs_no_key(tmp_path, monkeypatch):
    r = make(tmp_path, monkeypatch)
    code, got = r.run("--check")
    assert code == 0 and got == {"ok": True, "source": "openverse", "kinds": ["image"], "licence_tier": "per-item", "secret": "none"}
    assert r.resolver.asked == [] and r.net.count() == 0


# --- licences --------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("licence,version,expected", [
    ("by", "4.0", "cc-by-4.0"), ("by", "3.0", "cc-by-3.0"), ("by", "2.5", "cc-by-2.5"), ("by", "2.0", "cc-by-2.0"), ("cc0", "1.0", "cc0-1.0"), ("pdm", "1.0", "pdm-1.0"),
    ("BY", " 4.0 ", "cc-by-4.0"), ("by", None, None), ("by", "", None), ("by", "1.0", None), ("by", "4.0 ", "cc-by-4.0"),
    ("by-sa", "4.0", None), ("by-sa", "3.0", None), ("by-nc", "4.0", None), ("by-nc-sa", "4.0", None), ("by-nd", "4.0", None), ("by-nc-nd", "4.0", None),
    ("sampling+", "1.0", None), ("cc0", None, None), ("pdm", "2.0", None), (None, "4.0", None), ("", "4.0", None), (5, "4.0", None)])
def test_each_licence_and_version_is_mapped_or_dropped(tmp_path, monkeypatch, licence, version, expected):
    r = serve(make(tmp_path, monkeypatch), [item(1, licence, version)])
    code, got = r.search("image", "quiet harbour", 3)
    assert code == 0
    if expected is None:
        assert got["candidates"] == [] and got["dropped"]["licence"] == 1 and got["previews"] == 0
        assert list(Path(r.out).iterdir()) == []                       # a dropped item's preview is never fetched
    else:
        assert [c["licence"] for c in got["candidates"]] == [expected] and got["dropped"]["licence"] == 0


def test_a_licence_that_asks_for_credit_and_has_no_author_is_dropped_but_a_free_one_is_kept(tmp_path, monkeypatch):
    r = serve(make(tmp_path, monkeypatch), [item(1, "by", "4.0", author=None), item(2, "by", "3.0", author=""), item(3, "cc0", "1.0", author=None),
                                            item(4, "pdm", "1.0", author=None), item(5, "by", "2.0", author=None), item(6, "by", "2.5", author="")])
    code, got = r.search("image", "quiet harbour", 6)
    assert code == 0 and sorted(c["licence"] for c in got["candidates"]) == ["cc0-1.0", "pdm-1.0"] and got["dropped"]["licence"] == 4


def test_a_source_file_whose_table_maps_to_a_refused_licence_is_refused_at_load(tmp_path, monkeypatch):
    for bad in ("cc-by-sa-4.0", "cc-by-nc-4.0", "cc-by-nd-4.0", "editorial-only", "unverified"):
        r = make(fresh(tmp_path, bad), monkeypatch, licences=dict(TABLE, **{"by-sa 4.0": bad}))
        code, got = r.run("--check")
        assert code == 1 and got["code"] == "licence_refused"
        assert r.net.count() == 0


def test_the_search_asks_for_the_licences_the_sources_and_no_mature_content(tmp_path, monkeypatch):
    r = serve(make(tmp_path, monkeypatch), [item(1)])
    code, got = r.search("image", "quiet harbour", 2)
    assert code == 0
    query = urllib.parse.parse_qs(urllib.parse.urlsplit("https://x" + r.net.api_requests()[0]["target"]).query)
    assert query["license"] == ["cc0,pdm,by"] and query["q"] == ["quiet harbour"] and query["mature"] == ["false"]
    assert query["source"] == ["flickr,wikimedia,stocksnap,rawpixel,nasa,met"] and "inaturalist" not in query["source"][0]
    assert "license_type" not in query and int(query["page_size"][0]) <= 20 and query["page_size"] == ["6"]


def test_the_search_never_asks_for_more_than_twenty_a_page():
    src = json.loads(COMMITTED.read_text(encoding="utf-8"))
    assert openverse.UPSTREAM_SOURCES == ("flickr", "wikimedia", "stocksnap", "rawpixel", "nasa", "met") and not hasattr(openverse, "LICENCE_TYPE")
    assert openverse.search_request(src, "image", "x", 50)[1]["page_size"] == "20"
    assert openverse.search_request(src, "image", "x", 9)[1]["page_size"] == "9"


# --- hosts -----------------------------------------------------------------------------------------------------------------------------

def test_an_item_whose_file_host_or_preview_host_is_not_listed_is_dropped(tmp_path, monkeypatch):
    r = serve(make(tmp_path, monkeypatch), [item(1), item(2, host="elsewhere.example"), item(3, thumb_host="elsewhere.example")])
    code, got = r.search("image", "quiet harbour", 6)
    assert code == 0 and [c["item"] for c in got["candidates"]] == [uid(1)] and got["dropped"]["host"] == 2
    assert r.net.count("elsewhere.example") == 0 and r.net.count(IMG) == 1


def test_an_item_with_a_page_that_is_not_https_keeps_no_page_but_stays(tmp_path, monkeypatch):
    bad = dict(item(1), foreign_landing_url="http://page.stock.example/x")
    r = serve(make(tmp_path, monkeypatch), [bad])
    code, got = r.search("image", "quiet harbour", 3)
    assert code == 0 and got["candidates"][0]["page"] == ""


def test_a_clip_is_not_served(tmp_path, monkeypatch):
    r = serve(make(tmp_path, monkeypatch), [item(1)])
    code, got = r.search("clip", "quiet harbour", 3)
    assert code == 2 and got["code"] == "query_refused" and r.net.count() == 0


def test_a_search_answer_that_is_not_the_expected_shape_gives_no_candidates(tmp_path, monkeypatch):
    for number, answer in enumerate(({"results": "x"}, {"results": [5, None, "a"]}, ["a"], {"nothing": 1})):
        r = make(fresh(tmp_path, "a%d" % number), monkeypatch)
        r.net.add(API, SEARCH, json_response(answer))
        code, got = r.search("image", "quiet harbour", 3)
        assert code == 0 and got["candidates"] == []


# --- no key ----------------------------------------------------------------------------------------------------------------------------

def test_no_key_is_looked_up_sent_or_kept(tmp_path, monkeypatch):
    r = serve(make(tmp_path, monkeypatch, cache_seconds=3600), [item(1)])
    r.environ["STOCK_OPENVERSE_API_KEY"] = kit.KEY
    assert r.search("image", "quiet harbour", 3)[0] == 0
    r.net.add(API, "/v2/pictures/%s/" % uid(1), json_response(item(1)))
    assert r.fetch("image", uid(1), 20_000_000)[0] == 0
    assert r.resolver.asked == []                                      # the resolver is never asked for anything
    for request in r.net.requests:
        assert set(k.lower() for k in request["headers"]) <= {"user-agent", "accept", "accept-encoding"}
    assert kit.KEY not in r.everything()


def test_a_source_file_that_names_a_secret_is_refused(tmp_path, monkeypatch):
    r = make(tmp_path, monkeypatch, secret="STOCK_OPENVERSE_API_KEY", secret_in="header")
    r.net.add(API, SEARCH, json_response({"results": []}))
    code, got = r.search()
    assert code == 3 and got["code"] == "source_not_ready" and got["fields"] == ["secret"] and r.net.count() == 0 and r.resolver.asked == []


# --- fetch -----------------------------------------------------------------------------------------------------------------------------

def test_fetch_reads_the_file_url_from_the_api_answer_and_keeps_the_items_licence(tmp_path, monkeypatch):
    r = make(tmp_path, monkeypatch)
    one = item(7, "by", "4.0")
    r.net.add(API, "/v2/pictures/%s/" % uid(7), json_response(one))
    r.net.add(IMG, "/f/%s.jpg" % uid(7), image_response())
    code, got = r.fetch("image", uid(7), 20_000_000)
    assert code == 0 and got["licence"] == "cc-by-4.0" and got["author"] == "Aster Lane" and got["file"] == "full-openverse-%s.jpg" % uid(7)
    assert (Path(r.out) / got["file"]).is_file()
    assert [q["host"] for q in r.net.requests] == [API, IMG]


def test_fetch_refuses_an_item_with_a_refused_licence_before_any_download(tmp_path, monkeypatch):
    r = make(tmp_path, monkeypatch)
    r.net.add(API, "/v2/pictures/%s/" % uid(8), json_response(item(8, "by-sa", "4.0")))
    code, got = r.fetch("image", uid(8), 20_000_000)
    assert code == 1 and got["code"] == "licence_refused" and r.net.count(IMG) == 0


def test_fetch_refuses_an_answer_for_another_item(tmp_path, monkeypatch):
    r = make(tmp_path, monkeypatch)
    r.net.add(API, "/v2/pictures/%s/" % uid(9), json_response(item(10)))
    code, got = r.fetch("image", uid(9), 20_000_000)
    assert code == 1 and got["code"] == "status" and r.net.count(IMG) == 0


def test_the_library_cannot_name_a_host_outside_the_list_for_the_full_file(tmp_path, monkeypatch):
    r = make(tmp_path, monkeypatch)
    r.net.add(API, "/v2/pictures/%s/" % uid(11), json_response(item(11, host="elsewhere.example")))
    code, got = r.fetch("image", uid(11), 20_000_000)
    assert code == 1 and got["code"] == "host_refused" and r.net.count("elsewhere.example") == 0


# --- Openverse is a source like another ------------------------------------------------------------------------------------------------

def test_the_licence_key_is_the_lower_case_name_and_the_version():
    assert openverse.licence_key({"license": "BY", "license_version": "4.0"}) == "by 4.0"
    assert openverse.licence_key({"license": "by"}) == "by"
    assert openverse.licence_key({"license": "by", "license_version": 4}) == "by"
    assert openverse.licence_key({"license_version": "4.0"}) is None and openverse.licence_key({"license": "  "}) is None


# --- the image path pattern of the committed file (K1, 2026-11-11) ---------------------------------------------------------------------

K1_PATHS = ("/3731/11907599844_507ae44b10_b.jpg", "/2370/2325882432_94b118903a.jpg", "/51/121209617_949ce54a9d_b.jpg",
            "/wikipedia/commons/b/b8/P%C3%B4r-do-sol_no_Vale_do_Rio_das_Antas_%285982770740%29.jpg")


def committed_pattern():
    return _stock.read_source(str(COMMITTED), COMMITTED_TODAY, "openverse", None)["_patterns"]["image"]


@pytest.mark.parametrize("path", K1_PATHS)
def test_the_three_flickr_paths_and_the_wikimedia_path_of_k1_match(path):
    assert committed_pattern().fullmatch(path)


@pytest.mark.parametrize("path", ["/3731/11907599844_507ae44b10_b.jpg/x", "/photos/3731/1_a.jpg", "/3731/1_a.gif", "/3731/1_a.svg", "/a/b.jpg", "/3731/1_ABC.jpg",
                                  "/wikipedia/commons/b/b8/../x.jpg", "/wikipedia/commons/b/b8/a..jpg", "/wikipedia/commons/b/b8/x.svg", "/wikipedia/commons/b/b8/x.jpg?a=1",
                                  "/wikipedia/commons/b/b8/dir/x.jpg", "/wikipedia/commons/bb/b8/x.jpg", "/wikipedia/en/b/b8/x.jpg", "/..", "/", ""])
def test_other_path_shapes_do_not_match(path):
    assert not committed_pattern().fullmatch(path)


def test_the_pattern_is_checked_on_the_files_host_and_path(tmp_path, monkeypatch):
    """The committed hosts and pattern, with the fake network: a listed host with an unknown path shape is dropped, and so is an unlisted host with a Flickr path."""
    src = json.loads(COMMITTED.read_text(encoding="utf-8"))
    r = Run(tmp_path, monkeypatch, source(**dict(src, terms_read_on="2026-11-01", api=dict(src["api"], host=API), media_hosts=[API, IMG, "upload.wikimedia.example"],
                                                 path_patterns={"preview": r"/t/[0-9a-f-]+\.jpg", "image": src["path_patterns"]["image"], "clip": None})),
            impl=openverse, resolver=kit.FakeResolver({}))

    def with_url(n, url):
        return dict(item(n), url=url)
    good = with_url(1, "https://%s/3731/11907599844_507ae44b10_b.jpg" % IMG)
    other_shape = with_url(2, "https://%s/photos/x.jpg" % IMG)
    other_host = with_url(3, "https://elsewhere.example/3731/11907599844_507ae44b10_b.jpg")
    with_dots = with_url(4, "https://%s/wikipedia/commons/b/b8/../x.jpg" % IMG)
    r.net.add(API, "/v1/images/", json_response({"results": [good, other_shape, other_host, with_dots]}))
    for i in (good, other_shape, other_host, with_dots):
        r.net.add(IMG, "/t/%s.jpg" % i["id"], image_response())
    code, got = r.search("image", "quiet harbour", 6)
    assert code == 0 and [c["item"] for c in got["candidates"]] == [uid(1)] and got["dropped"]["host"] == 3


# --- a URL that is not a plain https URL is refused by the implementation (the class matches the path alone) -------------------------------

CLEAN = "https://%s/f/%s.jpg" % (IMG, uid(1))


@pytest.mark.parametrize("bad", [CLEAN + "?x=1", CLEAN + "#f", "https://user@%s/f/%s.jpg" % (IMG, uid(1)), "https://%s:8443/f/%s.jpg" % (IMG, uid(1)),
                                 "http://%s/f/%s.jpg" % (IMG, uid(1)), CLEAN + "?", CLEAN + "#", None, 5])
@pytest.mark.parametrize("field", ["url", "thumbnail"])
def test_an_item_whose_url_or_thumbnail_is_not_a_plain_https_url_is_dropped(tmp_path, monkeypatch, field, bad):
    one = dict(item(1), **{field: bad})
    r = serve(make(tmp_path, monkeypatch), [one, item(2)])
    code, got = r.search("image", "quiet harbour", 6)
    assert code == 0 and [c["item"] for c in got["candidates"]] == [uid(2)] and got["dropped"]["host"] == 1


def test_fetch_refuses_a_file_url_with_a_query(tmp_path, monkeypatch):
    r = make(tmp_path, monkeypatch)
    r.net.add(API, "/v2/pictures/%s/" % uid(3), json_response(dict(item(3), url="https://%s/f/%s.jpg?x=1" % (IMG, uid(3)))))
    code, got = r.fetch("image", uid(3), 20_000_000)
    assert code == 1 and got["code"] == "host_refused" and r.net.count(IMG) == 0


def test_the_clean_k1_shaped_urls_still_pass_the_committed_rule():
    for url in ("https://live.staticflickr.com/3731/11907599844_507ae44b10_b.jpg", "https://upload.wikimedia.org" + K1_PATHS[3],
                "https://api.openverse.org/v1/images/%s/thumb/" % uid(1)):
        assert openverse._clean_url(url) == url


# --- the picture floor of this implementation (V9d glass layout, K1 size) ------------------------------------------------------------------

def test_the_floor_is_the_glass_layout_width_and_a_k1_sized_file_passes(tmp_path, monkeypatch):
    assert openverse.IMAGE_MIN == (950, 534) and _stock.FLOOR["image"] == (1080, 1350)       # the class floor is untouched
    r = serve(make(tmp_path, monkeypatch), [item(1, width=1024, height=768), item(2, width=949, height=700), item(3, width=1000, height=500),
                                            item(4, width=950, height=534), item(5, width=950, height=533)])
    code, got = r.search("image", "quiet harbour", 6)
    assert code == 0 and sorted(c["item"] for c in got["candidates"]) == [uid(1), uid(4)] and got["dropped"]["too_small"] == 3


def test_pexels_keeps_the_class_floor():
    import pexels
    assert pexels.IMAGE_MIN == _stock.FLOOR["image"] == (1080, 1350)      # Pexels keeps the class floor
