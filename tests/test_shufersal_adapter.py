from __future__ import annotations

import gzip
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grocery_agent.shufersal_adapter import (
    SHUFERSAL_INDEX_URL,
    ShufersalFeedError,
    ShufersalPublicPriceClient,
    _extract_price_feed_url,
    _token_matches,
    parse_price_catalog,
)


PUBLIC_FEED_URL = (
    "https://pricesprodpublic.blob.core.windows.net/pricefull/"
    "PriceFull7290027600007-002-413-20990101-030000.gz"
)

SYNTHETIC_XML = """\
<Root>
  <ChainID>7290027600007</ChainID>
  <StoreID>413</StoreID>
  <Items>
    <Item>
      <PriceUpdateTime>2099-01-01T03:00:00</PriceUpdateTime>
      <ItemCode>7290000000001</ItemCode>
      <ItemName>חלב בדיקה 3 אחוז</ItemName>
      <UnitQty>ליטר</UnitQty>
      <Quantity>1.00</Quantity>
      <UnitOfMeasure>ליטר</UnitOfMeasure>
      <bIsWeighted>0</bIsWeighted>
      <ItemPrice>7.20</ItemPrice>
      <UnitOfMeasurePrice>7.20</UnitOfMeasurePrice>
    </Item>
    <Item>
      <PriceUpdateTime>2099-01-01T03:00:00</PriceUpdateTime>
      <ItemCode>7290000000002</ItemCode>
      <ItemName>עגבניות בדיקה במשקל</ItemName>
      <UnitQty>קילוגרם</UnitQty>
      <Quantity>1.00</Quantity>
      <UnitOfMeasure>קילוגרם</UnitOfMeasure>
      <bIsWeighted>1</bIsWeighted>
      <ItemPrice>9.90</ItemPrice>
      <UnitOfMeasurePrice>9.90</UnitOfMeasurePrice>
    </Item>
  </Items>
</Root>
""".encode("utf-8")


class ShufersalAdapterTests(unittest.TestCase):
    def test_parses_official_price_fields_and_weight_marker(self) -> None:
        products = parse_price_catalog(SYNTHETIC_XML)

        self.assertEqual(len(products), 2)
        self.assertEqual(products[0].item_code, "7290000000001")
        self.assertEqual(str(products[0].price_ils), "7.20")
        self.assertFalse(products[0].weighted)
        self.assertTrue(products[1].weighted)

    def test_searches_by_hebrew_name_and_exact_item_code(self) -> None:
        index = f'<a href="{PUBLIC_FEED_URL}">download</a>'.encode()
        compressed = gzip.compress(SYNTHETIC_XML)
        calls: list[str] = []

        def fake_fetch(url: str, maximum_bytes: int) -> bytes:
            calls.append(url)
            return index if url == SHUFERSAL_INDEX_URL else compressed

        client = ShufersalPublicPriceClient(fetch_bytes=fake_fetch)

        self.assertEqual(client.search("חלב")[0].item_code, "7290000000001")
        self.assertEqual(
            client.search("7290000000002")[0].name,
            "עגבניות בדיקה במשקל",
        )
        self.assertEqual(calls.count(SHUFERSAL_INDEX_URL), 1)

    def test_search_token_does_not_match_a_longer_hebrew_word(self) -> None:
        milk = "\u05d7\u05dc\u05d1"
        halva = "\u05d7\u05dc\u05d1\u05d4"

        self.assertTrue(_token_matches(milk, milk))
        self.assertTrue(_token_matches(milk, milk + "3"))
        self.assertFalse(_token_matches(milk, halva))
    def test_rejects_unexpected_download_host(self) -> None:
        malicious = (
            '<a href="https://example.invalid/pricefull/'
            'PriceFull7290027600007-002-413-20990101-030000.gz">download</a>'
        )

        with self.assertRaises(ShufersalFeedError):
            _extract_price_feed_url(malicious)

    def test_rejects_wrong_store(self) -> None:
        wrong_store = SYNTHETIC_XML.replace(
            b"<StoreID>413</StoreID>",
            b"<StoreID>999</StoreID>",
        )

        with self.assertRaises(ShufersalFeedError):
            parse_price_catalog(wrong_store)


if __name__ == "__main__":
    unittest.main()
