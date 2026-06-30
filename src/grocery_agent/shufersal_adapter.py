from __future__ import annotations

import gzip
import html
import io
import re
import threading
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from grocery_agent.models import money


SHUFERSAL_ONLINE_STORE_ID = "413"
SHUFERSAL_CHAIN_ID = "7290027600007"
SHUFERSAL_INDEX_URL = (
    "https://prices.shufersal.co.il/"
    "FileObject/UpdateCategory?catID=2&storeId=413"
)
SHUFERSAL_BLOB_HOST = "pricesprodpublic.blob.core.windows.net"
MAX_COMPRESSED_BYTES = 5 * 1024 * 1024
MAX_XML_BYTES = 40 * 1024 * 1024
DEFAULT_CACHE_SECONDS = 30 * 60


class ShufersalFeedError(RuntimeError):
    pass


@dataclass(frozen=True)
class ShufersalProduct:
    item_code: str
    name: str
    price_ils: Decimal
    unit_quantity: str
    quantity: Decimal
    unit_of_measure: str
    unit_price_ils: Decimal
    weighted: bool
    updated_at: str


FetchBytes = Callable[[str, int], bytes]


class ShufersalPublicPriceClient:
    """Read-only client for Shufersal's official public price-transparency feed."""

    def __init__(
        self,
        fetch_bytes: FetchBytes | None = None,
        cache_seconds: int = DEFAULT_CACHE_SECONDS,
    ):
        self._fetch_bytes = fetch_bytes or _fetch_bytes
        self._cache_seconds = cache_seconds
        self._catalog: tuple[ShufersalProduct, ...] | None = None
        self._catalog_loaded_at = 0.0
        self._lock = threading.Lock()

    def catalog(self, refresh: bool = False) -> tuple[ShufersalProduct, ...]:
        with self._lock:
            cache_is_fresh = (
                self._catalog is not None
                and time.monotonic() - self._catalog_loaded_at < self._cache_seconds
            )
            if cache_is_fresh and not refresh:
                return self._catalog
            self._catalog = self._load_catalog()
            self._catalog_loaded_at = time.monotonic()
            return self._catalog

    def search(self, query: str, limit: int = 20) -> tuple[ShufersalProduct, ...]:
        normalized_query = _normalize(query)
        if not normalized_query:
            return ()

        products = self.catalog()
        if normalized_query.isdigit():
            exact_codes = tuple(
                product for product in products if product.item_code == normalized_query
            )
            if exact_codes:
                return exact_codes[:limit]

        query_tokens = normalized_query.split()
        candidates: list[tuple[tuple[int, int, int, str], ShufersalProduct]] = []
        for product in products:
            normalized_name = _normalize(product.name)
            name_tokens = normalized_name.split()
            if not all(
                any(_token_matches(token, name_token) for name_token in name_tokens)
                for token in query_tokens
            ):
                continue
            score = (
                0 if normalized_name == normalized_query else 1,
                0 if normalized_name.startswith(normalized_query) else 1,
                abs(len(normalized_name) - len(normalized_query)),
                normalized_name,
            )
            candidates.append((score, product))
        candidates.sort(key=lambda candidate: candidate[0])
        return tuple(product for _, product in candidates[:limit])

    def _load_catalog(self) -> tuple[ShufersalProduct, ...]:
        try:
            index_html = self._fetch_bytes(SHUFERSAL_INDEX_URL, 2 * 1024 * 1024)
            download_url = _extract_price_feed_url(index_html.decode("utf-8-sig"))
            compressed = self._fetch_bytes(download_url, MAX_COMPRESSED_BYTES)
            xml_bytes = _decompress_limited(compressed)
            return parse_price_catalog(xml_bytes)
        except ShufersalFeedError:
            raise
        except Exception as exc:
            raise ShufersalFeedError(
                "\u05dc\u05d0 \u05e0\u05d9\u05ea\u05df \u05dc\u05d8\u05e2\u05d5\u05df \u05db\u05e8\u05d2\u05e2 \u05d0\u05ea \u05de\u05d7\u05d9\u05e8\u05d9 \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc."
            ) from exc


def parse_price_catalog(xml_bytes: bytes) -> tuple[ShufersalProduct, ...]:
    try:
        root = ET.fromstring(xml_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, ET.ParseError) as exc:
        raise ShufersalFeedError(
            "\u05e7\u05d5\u05d1\u05e5 \u05d4\u05de\u05d7\u05d9\u05e8\u05d9\u05dd \u05e9\u05dc \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc \u05d0\u05d9\u05e0\u05d5 \u05ea\u05e7\u05d9\u05df."
        ) from exc

    if _text(root, "ChainID") != SHUFERSAL_CHAIN_ID:
        raise ShufersalFeedError(
            "\u05de\u05d6\u05d4\u05d4 \u05e8\u05e9\u05ea \u05dc\u05d0 \u05ea\u05e7\u05d9\u05df \u05d1\u05e7\u05d5\u05d1\u05e5 \u05d4\u05de\u05d7\u05d9\u05e8\u05d9\u05dd."
        )
    if _text(root, "StoreID") != SHUFERSAL_ONLINE_STORE_ID:
        raise ShufersalFeedError(
            "\u05e7\u05d5\u05d1\u05e5 \u05d4\u05de\u05d7\u05d9\u05e8\u05d9\u05dd \u05d0\u05d9\u05e0\u05d5 \u05e9\u05dc \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc ONLINE."
        )

    products: list[ShufersalProduct] = []
    for item in root.findall("./Items/Item"):
        try:
            item_code = _item_text(item, "ItemCode")
            name = _item_text(item, "ItemName")
            if not item_code or not name:
                continue
            products.append(
                ShufersalProduct(
                    item_code=item_code,
                    name=name,
                    price_ils=money(Decimal(_item_text(item, "ItemPrice"))),
                    unit_quantity=_item_text(item, "UnitQty"),
                    quantity=Decimal(_item_text(item, "Quantity") or "1"),
                    unit_of_measure=_item_text(item, "UnitOfMeasure"),
                    unit_price_ils=money(
                        Decimal(_item_text(item, "UnitOfMeasurePrice") or "0")
                    ),
                    weighted=_item_text(item, "bIsWeighted") == "1",
                    updated_at=_item_text(item, "PriceUpdateTime"),
                )
            )
        except (InvalidOperation, ValueError):
            continue
    if not products:
        raise ShufersalFeedError(
            "\u05e7\u05d5\u05d1\u05e5 \u05d4\u05de\u05d7\u05d9\u05e8\u05d9\u05dd \u05d0\u05d9\u05e0\u05d5 \u05de\u05db\u05d9\u05dc \u05de\u05d5\u05e6\u05e8\u05d9\u05dd."
        )
    return tuple(products)


def _extract_price_feed_url(index_html: str) -> str:
    hrefs = re.findall(r'href="([^"]+)"', index_html, flags=re.IGNORECASE)
    for encoded_href in hrefs:
        candidate = html.unescape(encoded_href)
        parsed = urlparse(candidate)
        if (
            parsed.scheme == "https"
            and parsed.hostname == SHUFERSAL_BLOB_HOST
            and parsed.path.startswith("/pricefull/")
            and "PriceFull" in parsed.path
            and f"-{SHUFERSAL_ONLINE_STORE_ID}-" in parsed.path
        ):
            return candidate
    raise ShufersalFeedError(
        "\u05dc\u05d0 \u05e0\u05de\u05e6\u05d0 \u05e7\u05d5\u05d1\u05e5 \u05de\u05d7\u05d9\u05e8\u05d9\u05dd \u05e2\u05d3\u05db\u05e0\u05d9 \u05dc\u05e9\u05d5\u05e4\u05e8\u05e1\u05dc ONLINE."
    )


def _fetch_bytes(url: str, maximum_bytes: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "GroceryAgent/1.0 public-price-reader"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            declared_length = response.headers.get("Content-Length")
            if declared_length and int(declared_length) > maximum_bytes:
                raise ShufersalFeedError(
                    "\u05e7\u05d5\u05d1\u05e5 \u05d4\u05de\u05d7\u05d9\u05e8\u05d9\u05dd \u05d2\u05d3\u05d5\u05dc \u05de\u05d4\u05de\u05d5\u05ea\u05e8."
                )
            payload = response.read(maximum_bytes + 1)
    except ShufersalFeedError:
        raise
    except Exception as exc:
        raise ShufersalFeedError(
            "\u05e9\u05d9\u05e8\u05d5\u05ea \u05de\u05d7\u05d9\u05e8\u05d9 \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc \u05d0\u05d9\u05e0\u05d5 \u05d6\u05de\u05d9\u05df \u05db\u05e8\u05d2\u05e2."
        ) from exc
    if len(payload) > maximum_bytes:
        raise ShufersalFeedError(
            "\u05e7\u05d5\u05d1\u05e5 \u05d4\u05de\u05d7\u05d9\u05e8\u05d9\u05dd \u05d2\u05d3\u05d5\u05dc \u05de\u05d4\u05de\u05d5\u05ea\u05e8."
        )
    return payload


def _decompress_limited(compressed: bytes) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as archive:
            payload = archive.read(MAX_XML_BYTES + 1)
    except (OSError, EOFError) as exc:
        raise ShufersalFeedError(
            "\u05e7\u05d5\u05d1\u05e5 \u05d4\u05de\u05d7\u05d9\u05e8\u05d9\u05dd \u05d4\u05d3\u05d7\u05d5\u05e1 \u05d0\u05d9\u05e0\u05d5 \u05ea\u05e7\u05d9\u05df."
        ) from exc
    if len(payload) > MAX_XML_BYTES:
        raise ShufersalFeedError(
            "\u05e7\u05d5\u05d1\u05e5 \u05d4\u05de\u05d7\u05d9\u05e8\u05d9\u05dd \u05d4\u05de\u05e4\u05d5\u05e8\u05e1 \u05d2\u05d3\u05d5\u05dc \u05de\u05d4\u05de\u05d5\u05ea\u05e8."
        )
    return payload


def _token_matches(query_token: str, name_token: str) -> bool:
    if name_token == query_token:
        return True
    suffix = name_token[len(query_token):] if name_token.startswith(query_token) else ""
    return bool(suffix) and suffix[0].isdigit()

def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w\u0590-\u05ff]+", " ", normalized)
    return " ".join(normalized.split())


def _text(root: ET.Element, tag: str) -> str:
    node = root.find(tag)
    return (node.text or "").strip() if node is not None else ""


def _item_text(item: ET.Element, tag: str) -> str:
    node = item.find(tag)
    return (node.text or "").strip() if node is not None else ""
