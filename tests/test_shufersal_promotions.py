from __future__ import annotations

import gzip
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grocery_agent.shufersal_adapter import ShufersalFeedError, ShufersalProduct
from grocery_agent.shufersal_basket import ShufersalBasketStore
from grocery_agent.shufersal_promotions import (
    SHUFERSAL_PROMOTIONS_INDEX_URL,
    ShufersalProductOffer,
    ShufersalPublicOfferClient,
    _extract_promotions_feed_url,
    parse_promotions,
)


ITEM_CODE = "7290000000001"
PROMOTION_URL = (
    "https://pricesprodpublic.blob.core.windows.net/promofull/"
    "PromoFull7290027600007-002-413-20990101-030000.gz"
)


def _promotion_xml(
    *,
    minimum_quantity: str = "1",
    discounted_price: str = "8.50",
    club_id: str = "0",
    coupon: str = "0",
) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Root>
  <ChainID>7290027600007</ChainID>
  <StoreID>413</StoreID>
  <Promotions>
    <Promotion>
      <PromotionID>promo-test</PromotionID>
      <PromotionDescription>synthetic public promotion</PromotionDescription>
      <PromotionStartDateTime>2099-01-01T00:00:00</PromotionStartDateTime>
      <PromotionEndDateTime>2099-01-02T00:00:00</PromotionEndDateTime>
      <ClubID>{club_id}</ClubID>
      <AdditionalIsCoupon>{coupon}</AdditionalIsCoupon>
      <Groups><Group><PromotionItems><PromotionItem>
        <ItemCode>{ITEM_CODE}</ItemCode>
        <MinQty>{minimum_quantity}</MinQty>
        <MaxQty>99</MaxQty>
        <DiscountRate>0</DiscountRate>
        <DiscountedPrice>{discounted_price}</DiscountedPrice>
        <bIsWeighted>0</bIsWeighted>
      </PromotionItem></PromotionItems></Group></Groups>
    </Promotion>
  </Promotions>
</Root>""".encode("utf-8")


def _product(*, weighted: bool = False) -> ShufersalProduct:
    return ShufersalProduct(
        item_code=ITEM_CODE,
        name="synthetic product",
        price_ils=Decimal("10.00"),
        unit_quantity="unit",
        quantity=Decimal("1"),
        unit_of_measure="unit",
        unit_price_ils=Decimal("10.00"),
        weighted=weighted,
        updated_at="2099-01-01T03:00:00",
    )


class _PriceClient:
    def __init__(self, product: ShufersalProduct):
        self.product = product

    def search(self, query: str, limit: int = 20) -> tuple[ShufersalProduct, ...]:
        return (self.product,) if query else ()


class ShufersalPromotionTests(unittest.TestCase):
    def _client(self, xml: bytes, product: ShufersalProduct | None = None) -> ShufersalPublicOfferClient:
        compressed = gzip.compress(xml)

        def fake_fetch(url: str, maximum_bytes: int) -> bytes:
            if url == SHUFERSAL_PROMOTIONS_INDEX_URL:
                return f'<a href="{PROMOTION_URL}">feed</a>'.encode()
            if url == PROMOTION_URL:
                return compressed
            raise AssertionError(f"unexpected synthetic URL: {url}")

        return ShufersalPublicOfferClient(
            price_client=_PriceClient(product or _product()),
            fetch_bytes=fake_fetch,
            cache_seconds=60,
        )

    def test_parses_public_promotion_and_applies_simple_price(self) -> None:
        offers = self._client(_promotion_xml()).search("synthetic")

        self.assertEqual(offers[0].effective_price_ils, Decimal("8.50"))
        self.assertEqual(offers[0].promotions[0].promotion_id, "promo-test")

    def test_quantity_club_and_coupon_promotions_are_not_auto_applied(self) -> None:
        for xml in (
            _promotion_xml(minimum_quantity="2"),
            _promotion_xml(club_id="7"),
            _promotion_xml(coupon="1"),
        ):
            with self.subTest(xml=xml):
                offer = self._client(xml).search("synthetic")[0]
                self.assertEqual(offer.effective_price_ils, Decimal("10.00"))
                self.assertEqual(len(offer.promotions), 1)

    def test_rejects_untrusted_or_wrong_store_promotion_url(self) -> None:
        with self.assertRaises(ShufersalFeedError):
            _extract_promotions_feed_url(
                '<a href="https://example.test/promofull/PromoFull-413-file.gz">feed</a>'
            )
        with self.assertRaises(ShufersalFeedError):
            _extract_promotions_feed_url(
                "https://pricesprodpublic.blob.core.windows.net/promofull/"
                "PromoFull7290027600007-002-999-20990101-030000.gz"
            )

    def test_rejects_wrong_store_in_promotion_xml(self) -> None:
        xml = _promotion_xml().replace(b"<StoreID>413</StoreID>", b"<StoreID>999</StoreID>")
        with self.assertRaises(ShufersalFeedError):
            parse_promotions(xml)

    def test_basket_totals_use_safe_public_price_and_marks_weighted_items(self) -> None:
        offer = ShufersalProductOffer(
            product=_product(weighted=True),
            promotions=(),
            effective_price_ils=Decimal("8.50"),
        )
        store = ShufersalBasketStore()

        basket = store.add("michal", offer, "2")

        self.assertEqual(basket.regular_total_ils, Decimal("20.00"))
        self.assertEqual(basket.estimated_total_ils, Decimal("17.00"))
        self.assertEqual(basket.public_savings_ils, Decimal("3.00"))
        self.assertTrue(basket.has_weighted_items)

    def test_baskets_are_isolated_by_actor(self) -> None:
        offer = ShufersalProductOffer(_product(), (), Decimal("10.00"))
        store = ShufersalBasketStore()

        store.add("michal", offer, "1")

        self.assertEqual(len(store.get("michal").lines), 1)
        self.assertEqual(len(store.get("shay").lines), 0)


if __name__ == "__main__":
    unittest.main()
