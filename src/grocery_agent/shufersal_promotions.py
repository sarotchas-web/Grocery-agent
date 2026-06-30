from __future__ import annotations

import html
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from grocery_agent.models import money
from grocery_agent.shufersal_adapter import (
    DEFAULT_CACHE_SECONDS,
    MAX_COMPRESSED_BYTES,
    SHUFERSAL_BLOB_HOST,
    SHUFERSAL_CHAIN_ID,
    SHUFERSAL_ONLINE_STORE_ID,
    ShufersalFeedError,
    ShufersalProduct,
    ShufersalPublicPriceClient,
    _decompress_limited,
)


SHUFERSAL_PROMOTIONS_INDEX_URL = (
    "https://prices.shufersal.co.il/"
    "FileObject/UpdateCategory?catID=4&storeId=413"
)


@dataclass(frozen=True)
class ShufersalPromotionItem:
    item_code: str
    minimum_quantity: Decimal
    maximum_quantity: Decimal
    discount_rate: Decimal
    discounted_price_ils: Decimal
    weighted: bool


@dataclass(frozen=True)
class ShufersalPromotion:
    promotion_id: str
    description: str
    starts_at: str
    ends_at: str
    club_only: bool
    coupon_required: bool
    items: tuple[ShufersalPromotionItem, ...]


@dataclass(frozen=True)
class ShufersalProductOffer:
    product: ShufersalProduct
    promotions: tuple[ShufersalPromotion, ...]
    effective_price_ils: Decimal


FetchBytes = Callable[[str, int], bytes]


class ShufersalPublicOfferClient:
    """Combines public prices with public promotion metadata for store 413."""

    def __init__(
        self,
        price_client: ShufersalPublicPriceClient | None = None,
        fetch_bytes: FetchBytes | None = None,
        cache_seconds: int = DEFAULT_CACHE_SECONDS,
    ):
        self._price_client = price_client or ShufersalPublicPriceClient()
        self._fetch_bytes = fetch_bytes or _fetch_bytes
        self._cache_seconds = cache_seconds
        self._promotions: tuple[ShufersalPromotion, ...] | None = None
        self._promotions_loaded_at = 0.0
        self._lock = threading.Lock()

    def search(self, query: str, limit: int = 20) -> tuple[ShufersalProductOffer, ...]:
        products = self._price_client.search(query, limit=limit)
        promotions_by_item: dict[str, list[ShufersalPromotion]] = {}
        for promotion in self.promotions():
            for item in promotion.items:
                promotions_by_item.setdefault(item.item_code, []).append(promotion)

        offers: list[ShufersalProductOffer] = []
        for product in products:
            relevant = tuple(promotions_by_item.get(product.item_code, ()))
            effective_price = product.price_ils
            for promotion in relevant:
                for item in promotion.items:
                    if item.item_code != product.item_code:
                        continue
                    if promotion.club_only or promotion.coupon_required:
                        continue
                    if item.minimum_quantity > Decimal("1"):
                        continue
                    if Decimal("0") < item.discounted_price_ils < effective_price:
                        effective_price = item.discounted_price_ils
            offers.append(
                ShufersalProductOffer(
                    product=product,
                    promotions=relevant,
                    effective_price_ils=money(effective_price),
                )
            )
        return tuple(offers)

    def promotions(self, refresh: bool = False) -> tuple[ShufersalPromotion, ...]:
        with self._lock:
            cache_is_fresh = (
                self._promotions is not None
                and time.monotonic() - self._promotions_loaded_at < self._cache_seconds
            )
            if cache_is_fresh and not refresh:
                return self._promotions
            self._promotions = self._load_promotions()
            self._promotions_loaded_at = time.monotonic()
            return self._promotions

    def _load_promotions(self) -> tuple[ShufersalPromotion, ...]:
        try:
            index_html = self._fetch_bytes(
                SHUFERSAL_PROMOTIONS_INDEX_URL,
                2 * 1024 * 1024,
            )
            download_url = _extract_promotions_feed_url(
                index_html.decode("utf-8-sig")
            )
            compressed = self._fetch_bytes(download_url, MAX_COMPRESSED_BYTES)
            return parse_promotions(_decompress_limited(compressed))
        except ShufersalFeedError:
            raise
        except Exception as exc:
            raise ShufersalFeedError(
                "\u05dc\u05d0 \u05e0\u05d9\u05ea\u05df \u05dc\u05d8\u05e2\u05d5\u05df \u05db\u05e8\u05d2\u05e2 \u05d0\u05ea \u05de\u05d1\u05e6\u05e2\u05d9 \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc."
            ) from exc


def parse_promotions(xml_bytes: bytes) -> tuple[ShufersalPromotion, ...]:
    try:
        root = ET.fromstring(xml_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, ET.ParseError) as exc:
        raise ShufersalFeedError(
            "\u05e7\u05d5\u05d1\u05e5 \u05d4\u05de\u05d1\u05e6\u05e2\u05d9\u05dd \u05e9\u05dc \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc \u05d0\u05d9\u05e0\u05d5 \u05ea\u05e7\u05d9\u05df."
        ) from exc

    if _text(root, "ChainID") != SHUFERSAL_CHAIN_ID:
        raise ShufersalFeedError(
            "\u05de\u05d6\u05d4\u05d4 \u05e8\u05e9\u05ea \u05dc\u05d0 \u05ea\u05e7\u05d9\u05df \u05d1\u05e7\u05d5\u05d1\u05e5 \u05d4\u05de\u05d1\u05e6\u05e2\u05d9\u05dd."
        )
    if _text(root, "StoreID") != SHUFERSAL_ONLINE_STORE_ID:
        raise ShufersalFeedError(
            "\u05e7\u05d5\u05d1\u05e5 \u05d4\u05de\u05d1\u05e6\u05e2\u05d9\u05dd \u05d0\u05d9\u05e0\u05d5 \u05e9\u05dc \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc ONLINE."
        )

    promotions: list[ShufersalPromotion] = []
    for node in root.findall("./Promotions/Promotion"):
        promotion_items: list[ShufersalPromotionItem] = []
        for item in node.findall("./Groups/Group/PromotionItems/PromotionItem"):
            item_code = _text(item, "ItemCode")
            if not item_code:
                continue
            try:
                promotion_items.append(
                    ShufersalPromotionItem(
                        item_code=item_code,
                        minimum_quantity=_decimal(_text(item, "MinQty")),
                        maximum_quantity=_decimal(_text(item, "MaxQty")),
                        discount_rate=_decimal(_text(item, "DiscountRate")),
                        discounted_price_ils=money(
                            _decimal(_text(item, "DiscountedPrice"))
                        ),
                        weighted=_text(item, "bIsWeighted") == "1",
                    )
                )
            except InvalidOperation:
                continue
        if not promotion_items:
            continue
        promotions.append(
            ShufersalPromotion(
                promotion_id=_text(node, "PromotionID"),
                description=_text(node, "PromotionDescription"),
                starts_at=_text(node, "PromotionStartDateTime"),
                ends_at=_text(node, "PromotionEndDateTime"),
                club_only=_text(node, "ClubID") not in ("", "0"),
                coupon_required=_text(node, "AdditionalIsCoupon") == "1",
                items=tuple(promotion_items),
            )
        )
    return tuple(promotions)


def _extract_promotions_feed_url(index_html: str) -> str:
    hrefs = re.findall(r'href="([^"]+)"', index_html, flags=re.IGNORECASE)
    for encoded_href in hrefs:
        candidate = html.unescape(encoded_href)
        parsed = urlparse(candidate)
        if (
            parsed.scheme == "https"
            and parsed.hostname == SHUFERSAL_BLOB_HOST
            and parsed.path.startswith("/promofull/")
            and "PromoFull" in parsed.path
            and f"-{SHUFERSAL_ONLINE_STORE_ID}-" in parsed.path
        ):
            return candidate
    raise ShufersalFeedError(
        "\u05dc\u05d0 \u05e0\u05de\u05e6\u05d0 \u05e7\u05d5\u05d1\u05e5 \u05de\u05d1\u05e6\u05e2\u05d9\u05dd \u05e2\u05d3\u05db\u05e0\u05d9 \u05dc\u05e9\u05d5\u05e4\u05e8\u05e1\u05dc ONLINE."
    )


def _fetch_bytes(url: str, maximum_bytes: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "GroceryAgent/1.0 public-promotion-reader"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            declared_length = response.headers.get("Content-Length")
            if declared_length and int(declared_length) > maximum_bytes:
                raise ShufersalFeedError(
                    "\u05e7\u05d5\u05d1\u05e5 \u05d4\u05de\u05d1\u05e6\u05e2\u05d9\u05dd \u05d2\u05d3\u05d5\u05dc \u05de\u05d4\u05de\u05d5\u05ea\u05e8."
                )
            payload = response.read(maximum_bytes + 1)
    except ShufersalFeedError:
        raise
    except Exception as exc:
        raise ShufersalFeedError(
            "\u05e9\u05d9\u05e8\u05d5\u05ea \u05de\u05d1\u05e6\u05e2\u05d9 \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc \u05d0\u05d9\u05e0\u05d5 \u05d6\u05de\u05d9\u05df \u05db\u05e8\u05d2\u05e2."
        ) from exc
    if len(payload) > maximum_bytes:
        raise ShufersalFeedError(
            "\u05e7\u05d5\u05d1\u05e5 \u05d4\u05de\u05d1\u05e6\u05e2\u05d9\u05dd \u05d2\u05d3\u05d5\u05dc \u05de\u05d4\u05de\u05d5\u05ea\u05e8."
        )
    return payload


def _decimal(value: str) -> Decimal:
    return Decimal(value or "0")


def _text(root: ET.Element, tag: str) -> str:
    node = root.find(tag)
    return (node.text or "").strip() if node is not None else ""
