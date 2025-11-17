"""Utility helpers for OpenAI-compatible clients."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

import httpx


def normalize_openai_base_url(base_url: str | httpx.URL | None) -> str | None:
	"""
	Normalize an OpenAI-compatible base URL.

	This helper makes LiteLLM/OpenAI proxies work out-of-the-box by:
	- Handling httpx.URL instances
	- Adding a default scheme when missing (http for localhost, https otherwise)
	- Ensuring the URL ends with `/v1` when no version segment is present
	"""
	if base_url is None:
		return None

	base_str = str(base_url).strip()
	if not base_str:
		return None

	# Add scheme if it is missing
	if not base_str.lower().startswith(('http://', 'https://')):
		if base_str.lower().startswith(('localhost', '127.', '0.0.0.0', '::1')):
			base_str = f'http://{base_str}'
		else:
			base_str = f'https://{base_str}'

	parsed = urlparse(base_str)
	path = (parsed.path or '').rstrip('/')
	segments = [segment for segment in path.split('/') if segment]

	def _has_version_segment(parts: list[str]) -> bool:
		for segment in parts:
			seg = segment.lower()
			if len(seg) > 1 and seg.startswith('v') and seg[1].isdigit():
				return True
		return False

	if not _has_version_segment(segments):
		path = f'{path}/v1' if path else '/v1'
		parsed = parsed._replace(path=path)

	return urlunparse(parsed)

