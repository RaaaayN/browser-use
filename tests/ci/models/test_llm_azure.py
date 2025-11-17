"""Test Azure OpenAI model button click."""

from browser_use.llm.azure.chat import ChatAzureOpenAI
from tests.ci.models.model_test_helper import run_model_button_click_test


async def test_azure_gpt_4_1_mini(httpserver):
	"""Test Azure OpenAI gemini-2.5-flash-lite-preview-09-2025-thinking can click a button."""
	await run_model_button_click_test(
		model_class=ChatAzureOpenAI,
		model_name='gemini-2.5-flash-lite-preview-09-2025-thinking',
		api_key_env='AZURE_OPENAI_KEY',
		extra_kwargs={},  # Azure endpoint will be added by helper
		httpserver=httpserver,
	)
