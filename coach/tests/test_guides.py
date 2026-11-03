"""Module registry: front-matter parsing, lookup, index, trigger mapping —
the pull side of the hybrid knowledge system (push = deterministic hints
on tool results)."""
from coach import guides


def test_modules_load_with_metadata():
    mods = guides.load_modules()
    assert "git-leak" in mods
    m = mods["git-leak"]
    assert "object-walk" in m.title.lower()
    assert ".git/" in m.triggers
    assert "wget -r" in m.body            # verbatim recipe preserved
    assert len(mods) >= 8


def test_index_one_line_per_module():
    idx = guides.index()
    assert "git-leak — " in idx
    assert "pivoting — " in idx
    # index is prompt-bound — must stay compact
    assert len(idx) < 2000


def test_lookup_by_id_and_keyword():
    body = guides.lookup("git-leak")
    assert "zlib.decompress" in body          # the verbatim snippet
    by_topic = guides.lookup("multi-hop")
    assert "ProxyCommand" in by_topic or "pivot" in by_topic.lower()


def test_lookup_unknown_names_known_ids():
    res = guides.lookup("totally-bogus")
    assert res.startswith("error: unknown guide")
    assert "git-leak" in res


def test_lookup_empty_query_lists_index():
    res = guides.lookup("")
    assert "known guides" in res
    assert "wifi-lab" in res


def test_triggers_for_maps_observations():
    assert "git-leak" in guides.triggers_for(
        "gobuster found: /.git/ (Status: 301)")
    assert "pivoting" in guides.triggers_for(
        "22/tcp   filtered ssh\n80/tcp   filtered http")
    assert "minimal-hosts" in guides.triggers_for(
        "bash: curl: command not found")
    assert "wifi-lab" in guides.triggers_for(
        "airodump-ng -w out --bssid AA wlan0")
    assert guides.triggers_for("cat /etc/hostname") == []
    # deduped — a module fires once per call even with multiple keywords
    hits = guides.triggers_for(".git/ .git/logs/HEAD refs/heads/master")
    assert hits.count("git-leak") == 1
