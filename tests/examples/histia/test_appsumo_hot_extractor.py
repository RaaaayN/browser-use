from __future__ import annotations

from examples.histia.appsumo_hot_extractor import (
	_parse_html_sections,
	_parse_product_card,
)

SOURCE_URL = 'https://appsumo.com/collections/whats-hot/'

SAMPLE_CARD_HTML = """
<div class="relative h-full">
  <a href="/products/gumlet-video/" class="absolute h-full w-full text-[0px] after:pointer-events-auto after:absolute after:inset-0 after:z-[1] after:content-['']">
    <span class="sr-only">Gumlet Video</span>
  </a>
  <div class="flex grow flex-col pb-1 md:p-4 md:text-center">
    <div class="inline-flex h-[20px] w-fit max-w-[200px] rounded bg-[#eef9f1] px-2 py-1 max-md:order-1 max-md:mt-2 md:mb-1 md:mx-auto">
      <img alt="AppSumo Select" src="https://appsumo2next-cdn.appsumo.com/_next/static/media/appsumo-select.fa569648.svg">
    </div>
    <span class="font-bold">Gumlet Video</span>
    <span>in <a href="/software/media-tools/video/" class="relative z-1 underline">Video</a></span>
    <div class="my-1 line-clamp-3">Host, secure, and stream videos with a personalized player in minutes</div>
  </div>
  <div class="absolute bottom-0 left-0 w-full text-center text-xs font-bold text-white md:text-base bg-ready-red-dark-20 z-2">
    <span>Price increases in 4 days</span>
  </div>
  <div class="relative md:text-center">
    <div class="flex h-6 items-center gap-3 mb-2 justify-start md:justify-center">
      <span class="">
        <div class="flex items-center">
          <div class="relative mr-2 h-5 z-2">
            <img src="data:image/png;base64,test" alt="4.7 stars" class="h-full w-auto">
          </div>
        </div>
      </span>
    </div>
    <a href="/products/gumlet-video/#reviews" class="text-sm text-blue-600 hover:underline cursor-pointer z-2 whitespace-nowrap">
      <span>125 reviews</span>
    </a>
  </div>
  <div class="font-medium md:text-2xl">
    <div data-testid="deal-price-container">
      <span id="deal-price">$69</span>
      <span id="deal-price-suffix">/lifetime</span>
      <span id="deal-price-original">$300</span>
    </div>
  </div>
  <img alt="Gumlet Video" src="https://appsumo2-cdn.appsumo.com/media/deals/images/gumlet.png">
</div>
"""


def test_parse_product_card_extracts_expected_fields() -> None:
	product = _parse_product_card(SAMPLE_CARD_HTML, SOURCE_URL)
	assert product is not None
	assert product.name == 'Gumlet Video'
	assert product.product_url == 'https://appsumo.com/products/gumlet-video/'
	assert product.category == 'Video'
	assert product.category_url == 'https://appsumo.com/software/media-tools/video/'
	assert product.description.startswith('Host, secure')
	assert product.price == '$69'
	assert product.price_suffix == '/lifetime'
	assert product.original_price == '$300'
	assert product.reviews_count == 125
	assert product.rating_value == 4.7
	assert product.rating_text == '4.7 stars'
	assert product.appsumo_select is True
	assert 'Price increases in 4 days' in product.badges
	assert product.image_url == 'https://appsumo2-cdn.appsumo.com/media/deals/images/gumlet.png'


def test_parse_html_sections_builds_report() -> None:
	report = _parse_html_sections([SAMPLE_CARD_HTML], SOURCE_URL)
	assert report is not None
	assert str(report.source_url) == SOURCE_URL
	assert len(report.products) == 1
	assert report.products[0].name == 'Gumlet Video'


