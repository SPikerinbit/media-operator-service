from app import weread


READER = "https://weread.qq.com/web/reader/ce032b305a9bc1ce0b0dd2a"


def test_book_id_and_chapter_parsing():
    assert weread.book_id(READER) == "ce032b305a9bc1ce0b0dd2a"
    chapters = weread.chapters_from({"data": [{"updated": [
        {"chapterUid": 1, "title": "第一章"},
        {"chapterUid": 2, "title": "第二章"},
    ]}]})
    assert chapters == [{"uid": 1, "title": "第一章"}, {"uid": 2, "title": "第二章"}]
    body = weread.text_from_chapter({"content": "<p>宇宙很大。</p><p>句子要站得住。</p>"})
    assert "宇宙很大" in body and "<p>" not in body
    text = weread.assemble([
        {"title": "第一章", "text": body},
        {"title": "空章", "text": "  "},
    ])
    assert text.startswith("第一章")
    assert "空章" not in text


def test_fetch_without_cookies_does_not_call_the_network():
    try:
        weread.fetch_book(READER, "")
    except weread.LoginRequired as error:
        assert "登录" in str(error)
    else:
        raise AssertionError("expected login")


def test_netscape_cookie_header():
    raw = ".weread.qq.com\tTRUE\t/\tTRUE\t0\twr_skey\tsecret-value\n"
    assert weread.cookie_header(raw) == "wr_skey=secret-value"
