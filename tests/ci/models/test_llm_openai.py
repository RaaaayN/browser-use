"""Test OpenAI model button click."""

from browser_use.llm.openai.chat import ChatOpenAI
from tests.ci.models.model_test_helper import run_model_button_click_test


async def test_openai_gpt_4_1_mini(httpserver):
	"""Test OpenAI gemini-2.5-flash-lite-preview-09-2025-thinking can click a button."""
	await run_model_button_click_test(
		model_class=ChatOpenAI,
		model_name='gemini-2.5-flash-lite-preview-09-2025-thinking',
		api_key_env='OPENAI_API_KEY',
		extra_kwargs={},
		httpserver=httpserver,
	)
