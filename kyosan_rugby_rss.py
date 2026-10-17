import os
import re
import time
import hashlib
import requests
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import urljoin

SOURCE_URL = "https://kyosan-rugby.com/pg4111476.html"
OUTPUT_FILE = "kyosan_rugby.xml"

FEED_TITLE = "京都産業大学体育会ラグビー部 NEWS"
FEED_LINK = SOURCE_URL
FEED_DESCRIPTION = "京都産業大学体育会ラグビー部 NEWS 更新情報"

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
}

DATE_RE = re.compile(
    r"(20\d{2})\.(\d{1,2})\.(\d{1,2})"
)

ARTICLE_ID_RE = re.compile(r"^bk\d+$")


def fetch_page():
    last_error = None

    for attempt in range(1, 4):
        try:
            print(f"取得試行 {attempt}/3: {SOURCE_URL}")

            response = requests.get(
                SOURCE_URL,
                headers=HEADERS,
                timeout=30
            )

            print(
                f"HTTP: {response.status_code} / "
                f"取得バイト数: {len(response.content)}"
            )

            response.raise_for_status()

            response.encoding = response.apparent_encoding
            return response.text

        except Exception as e:
            last_error = e
            print(f"取得失敗: {e}")

            if attempt < 3:
                print("10秒待って再試行します。")
                time.sleep(10)

    raise RuntimeError(
        f"NEWSページを取得できませんでした: {last_error}"
    )


def make_guid(link):
    return hashlib.sha256(
        link.encode("utf-8")
    ).hexdigest()


def parse_date(text):
    match = DATE_RE.search(text)

    if not match:
        return None

    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))

    try:
        return datetime(
            year,
            month,
            day,
            12,
            0,
            0,
            tzinfo=JST
        )
    except ValueError:
        return None


def clean_text(text):
    return re.sub(r"\s+", " ", text).strip()


def extract_title(element, full_text, date_match):
    before_date = full_text[:date_match.start()].strip()

    if before_date:
        return clean_text(before_date)

    for tag in element.find_all(
        ["h1", "h2", "h3", "h4", "h5", "p", "div", "span"]
    ):
        text = clean_text(tag.get_text(" ", strip=True))

        if not text:
            continue

        if DATE_RE.search(text):
            continue

        if len(text) <= 200:
            return text

    return None


def extract_articles(html):
    soup = BeautifulSoup(html, "html.parser")

    articles = []
    seen_ids = set()

    candidates = soup.find_all(
        id=lambda value: (
            isinstance(value, str)
            and ARTICLE_ID_RE.fullmatch(value) is not None
        )
    )

    print(f"bk形式の候補数: {len(candidates)}")

    for element in candidates:
        article_id = element.get("id")

        if not article_id:
            continue

        if article_id in seen_ids:
            continue

        full_text = clean_text(
            element.get_text(" ", strip=True)
        )

        date_match = DATE_RE.search(full_text)

        if not date_match:
            continue

        published = parse_date(full_text)

        if published is None:
            continue

        title = extract_title(
            element,
            full_text,
            date_match
        )

        if not title:
            continue

        if len(title) > 250:
            continue

        link = f"{SOURCE_URL}#{article_id}"

        description_text = full_text[date_match.end():].strip()

        if len(description_text) > 1000:
            description_text = (
                description_text[:1000].rstrip()
                + "…"
            )

        articles.append({
            "title": title,
            "link": link,
            "guid": make_guid(link),
            "published": published,
            "description": description_text,
        })

        seen_ids.add(article_id)

    articles.sort(
        key=lambda x: x["published"],
        reverse=True
    )

    return articles


def load_existing():
    existing = {}

    if not os.path.exists(OUTPUT_FILE):
        return existing

    try:
        tree = ET.parse(OUTPUT_FILE)
        root = tree.getroot()

        for item in root.findall("./channel/item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            guid = item.findtext("guid", "").strip()
            pub_date = item.findtext("pubDate", "").strip()
            description = item.findtext(
                "description",
                ""
            ).strip()

            if not link:
                continue

            try:
                published = parsedate_to_datetime(
                    pub_date
                )

                if published.tzinfo is None:
                    published = published.replace(
                        tzinfo=JST
                    )

            except Exception:
                continue

            existing[link] = {
                "title": title,
                "link": link,
                "guid": guid or make_guid(link),
                "published": published,
                "description": description,
            }

    except Exception as e:
        print(f"既存RSS読み込み失敗: {e}")
        raise

    return existing


def build_rss(articles):
    rss = ET.Element(
        "rss",
        version="2.0"
    )

    channel = ET.SubElement(rss, "channel")

    ET.SubElement(
        channel,
        "title"
    ).text = FEED_TITLE

    ET.SubElement(
        channel,
        "link"
    ).text = FEED_LINK

    ET.SubElement(
        channel,
        "description"
    ).text = FEED_DESCRIPTION

    ET.SubElement(
        channel,
        "language"
    ).text = "ja"

    ET.SubElement(
        channel,
        "lastBuildDate"
    ).text = format_datetime(
        datetime.now(JST)
    )

    for article in articles:
        item = ET.SubElement(
            channel,
            "item"
        )

        ET.SubElement(
            item,
            "title"
        ).text = article["title"]

        ET.SubElement(
            item,
            "link"
        ).text = article["link"]

        guid = ET.SubElement(
            item,
            "guid"
        )
        guid.set("isPermaLink", "false")
        guid.text = article["guid"]

        ET.SubElement(
            item,
            "pubDate"
        ).text = format_datetime(
            article["published"]
        )

        ET.SubElement(
            item,
            "description"
        ).text = article["description"]

    tree = ET.ElementTree(rss)

    try:
        ET.indent(
            tree,
            space="  "
        )
    except AttributeError:
        pass

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True
    )


def main():
    existing = load_existing()

    print(f"既存RSS件数: {len(existing)}")

    try:
        html = fetch_page()
        current = extract_articles(html)

        print(f"現在ページから取得: {len(current)}件")

        if not current:
            raise RuntimeError(
                "記事を1件も抽出できませんでした。"
            )

        current_by_link = {
            article["link"]: article
            for article in current
        }

        new_count = sum(
            1
            for link in current_by_link
            if link not in existing
        )

        merged = dict(existing)
        merged.update(current_by_link)

        all_articles = list(
            merged.values()
        )

        all_articles.sort(
            key=lambda x: x["published"],
            reverse=True
        )

        print(f"新規記事: {new_count}件")
        print(f"累積RSS件数: {len(all_articles)}")

        print()
        print("最新30件:")

        for article in all_articles[:30]:
            print(
                article["published"]
                .astimezone(JST)
                .strftime("%Y-%m-%d"),
                article["title"]
            )

        build_rss(all_articles)

        print()
        print(
            f"保存完了: {OUTPUT_FILE} "
            f"({len(all_articles)}件)"
        )

    except Exception:
        print()
        print(
            "取得・解析に失敗したため、"
            "既存RSSは変更しません。"
        )
        raise


if __name__ == "__main__":
    main()