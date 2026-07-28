from app.services.listing_detail_service import (
    extract_listing_images,
    extract_visible_listing_text,
)


def test_extract_visible_listing_text_ignores_scripts_and_keeps_page_evidence():
    html = """
    <html>
      <head><style>.hidden { display:none }</style></head>
      <body>
        <h1>明亮套房</h1>
        <img src="https://example.com/room-1.jpg">
        <img data-src="https://example.com/room-2.jpg">
        <img src="https://example.com/logo.png">
        <div>房租含水費，可協助申請租金補貼，謝絕毛小孩。</div>
        <script>window.secret = "不應出現";</script>
      </body>
    </html>
    """

    text = extract_visible_listing_text(html)

    assert "房租含水費" in text
    assert "租金補貼" in text
    assert "謝絕毛小孩" in text
    assert "window.secret" not in text
    assert extract_listing_images(html) == [
        "https://example.com/room-1.jpg",
        "https://example.com/room-2.jpg",
    ]
