"""
Agent designed to build a lightweight list of startups from directories such as
Product Hunt, BetaList, FutureTools, etc.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import re
from pathlib import Path
from textwrap import dedent
from urllib.parse import urljoin, urlparse

import httpx
from dotenv import load_dotenv
from pydantic import AnyHttpUrl, BaseModel, Field, ValidationError

from browser_use import Agent, ChatBrowserUse, ChatOpenAI

# Load environment variables immediately so the agent can access API keys.
load_dotenv()
# Use slightly slower timeouts than defaults to let the agent finish scrolling/extractions.
os.environ.setdefault('TIMEOUT_ScreenshotEvent', '25')
os.environ.setdefault('TIMEOUT_BrowserStateRequestEvent', '45')


class StartupListingInput(BaseModel):
	"""User-provided parameters for the startup listing task."""

	url: AnyHttpUrl = Field(..., description='Product Hunt, BetaList, FutureTools, etc. listing URL')
	max_startups: int = Field(
		12,
		ge=1,
		le=40,
		description='Maximum number of startups to capture from the page',
	)
	output_path: Path = Field(
		default=Path('startup_listings.json'),
		description='Destination for the JSON list of startups',
	)


class StartupProfile(BaseModel):
	"""Minimal structured information for each startup entry."""

	name: str = Field(..., description='Startup name exactly as written on the listing')
	listing_url: str | None = Field(
		None,
		description='Direct URL to the startup page/product as exposed by the listing',
	)
	linkedin_url: str | None = Field(
		None,
		description='Public LinkedIn URL shown on the listing (keep None if absent)',
	)
	short_notes: list[str] = Field(
		default_factory=list,
		description='Two or three short bullet points from the listing (value proposition, positioning, tags, etc.)',
	)


class StartupListingReport(BaseModel):
	"""Complete response returned by the agent."""

	source_url: AnyHttpUrl = Field(..., description='URL that was analysed')
	startups: list[StartupProfile] = Field(
		...,
		min_length=1,
		description='Startup entries ordered as they appear on the listing',
	)


def _normalize_linkedin_url(value: str | None) -> str | None:
	"""Return a valid LinkedIn URL or None."""

	if not value:
		return None

	url = value.strip()
	if not url:
		return None

	if not url.lower().startswith(('http://', 'https://')):
		return None

	parsed = urlparse(url)
	if not parsed.netloc:
		return None

	if 'linkedin.com' not in parsed.netloc.lower():
		return None

	return url


def _fallback_report(source_url: str, reason: str) -> StartupListingReport:
	"""Return a minimal report when the agent cannot finish properly."""

	reason = reason.strip() or "Impossible d'obtenir un listing fiable depuis la page."
	from pydantic import AnyHttpUrl
	return StartupListingReport(
		source_url=AnyHttpUrl(source_url),
		startups=[
			StartupProfile(
				name='Informations indisponibles',
				listing_url=source_url,
				linkedin_url=None,
				short_notes=[
					reason,
					'Rapport généré automatiquement (agent interrompu avant la fin).',
				],
			)
		],
	)


def _normalize_listing_url(url: str | None, base_url: str) -> str | None:
	"""Convert relative URLs to absolute URLs."""
	if not url:
		return None
	
	url = url.strip()
	if not url:
		return None
	
	# If it's already an absolute URL, return as is
	if url.startswith(('http://', 'https://')):
		return url
	
	# If it starts with /, make it relative to the base domain
	if url.startswith('/'):
		parsed_base = urlparse(base_url)
		return f"{parsed_base.scheme}://{parsed_base.netloc}{url}"
	
	# Otherwise, try to resolve relative to base URL
	try:
		return urljoin(base_url, url)
	except Exception:
		return url


def _sanitize_report(report: StartupListingReport) -> StartupListingReport:
	"""Apply basic clean-up rules on top of the structured output."""

	base_url = str(report.source_url)
	for startup in report.startups:
		startup.linkedin_url = _normalize_linkedin_url(startup.linkedin_url)
		startup.listing_url = _normalize_listing_url(startup.listing_url, base_url)
		if startup.short_notes:
			startup.short_notes = [note.strip() for note in startup.short_notes if note.strip()]
	return report


def build_task(task_input: StartupListingInput) -> str:
	"""Create the natural-language instructions fed to the agent."""

	return dedent(
		f"""
		Tu es un analyste chargé de dresser un simple listing de startups à partir de la page {task_input.url}.

		Objectif:
		- Identifie jusqu'à {task_input.max_startups} startups ou produits présentés sur cette page.
		- Pour chaque entrée, capture:
		  • `name`: nom affiché.
		  • `listing_url`: URL exacte du bouton ou lien principal (utilise l'attribut href original, pas du texte).
		  • `linkedin_url`: URL LinkedIn si visible sur la page (laisse null sinon).
		  • `short_notes`: 2-3 infos très courtes depuis la page (tagline, cas d'usage, prix, catégorie, etc.).

		Processus recommandé:
		1. Scrolle la page plusieurs fois pour charger tous les listings (utilise `scroll` avec `down: true` et `pages: 1`).
		2. Utilise `extract` avec `extract_links=true` pour récupérer les données structurées des startups.
		3. Une fois que tu as collecté toutes les données, utilise l'action `done` avec le champ `data` contenant l'objet `StartupListingReport` complet.

		Règles importantes:
		- Reste strictement sur la page fournie; ne fais aucun aller-retour externe, aucune recherche additionnelle.
		- Scrolle l'intégralité du listing et n'oublie aucune carte pertinente.
		- À chaque appel `scroll`, fournis toujours `down` ET `pages` (ex: {{"scroll": {{"down": true, "pages": 1}}}}).
		- Lorsque tu extrais du texte, spécifie un champ `query`; pour récupérer des URLs, ajoute `extract_links=true`.
		- Les `short_notes` doivent être des phrases concises (<= 140 caractères) ou des puces factuelles, uniquement depuis le contenu affiché.
		- Si une info manque, laisse le champ vide (chaine vide) ou null, mais ne l'invente pas.
		- IMPORTANT: Pour terminer la tâche, utilise l'action `done` avec le format suivant:
		  {{"done": {{"success": true, "data": {{"source_url": "{task_input.url}", "startups": [...]}}}}}}
		- Le champ `data` de `done` doit contenir un objet `StartupListingReport` avec `source_url` et `startups` (liste de `StartupProfile`).
		- Chaque `StartupProfile` doit avoir `name`, `listing_url` (ou null), `linkedin_url` (ou null), et `short_notes` (liste de chaînes).
		- Exemple de format attendu pour `done`:
		  {{"done": {{"success": true, "data": {{
		    "source_url": "{task_input.url}",
		    "startups": [
		      {{
		        "name": "Nom de la startup",
		        "listing_url": "https://www.producthunt.com/products/...",
		        "linkedin_url": null,
		        "short_notes": ["Tagline", "Catégorie", "Prix"]
		      }}
		    ]
		  }}}}}}
		- Utilise la vision et sois patient si le chargement est lent; réessaie plutôt que d'abandonner.
		- Ne termine la tâche qu'après avoir construit l'objet `StartupListingReport` complet dans le champ `data` de `done`.
		"""
	).strip()


async def run_startup_listing(task_input: StartupListingInput) -> StartupListingReport | None:
	"""Execute the agent and return the structured list of startups."""

	print("🔧 Configuration du LLM...")
	if os.getenv('BROWSER_USE_API_KEY'):
		llm = ChatBrowserUse()
		print("✅ Utilisation de ChatBrowserUse")
	else:
		model_name = os.getenv('OPENAI_MODEL', 'gemini-2.5-flash-lite-preview-09-2025')
		# Pour les modèles Gemini via LiteLLM, utiliser add_schema_to_system_prompt
		# pour éviter les problèmes de schéma JSON avec response_format
		is_gemini = 'gemini' in model_name.lower()
		llm = ChatOpenAI(
			model=model_name,
			timeout=httpx.Timeout(180.0, connect=60.0, read=180.0, write=30.0),
			max_retries=3,  # Augmenté pour plus de robustesse avec Gemini
			add_schema_to_system_prompt=is_gemini,  # Évite les problèmes de schéma avec Gemini
			dont_force_structured_output=is_gemini,  # Gemini via LiteLLM a des problèmes avec response_format
		)
		print(f"✅ Utilisation de ChatOpenAI avec le modèle: {model_name}")
		if is_gemini:
			print("   ⚠️  Mode Gemini détecté: utilisation du schéma dans le prompt système")
			print("   💡 Note: Gemini peut parfois générer du JSON mal formé, mais les données seront récupérées depuis les extractions.")

	print("🤖 Création de l'agent...")
	agent = Agent(
		task=build_task(task_input),
		llm=llm,
		output_model_schema=StartupListingReport,
		use_vision=True,
		vision_detail_level='high',
		step_timeout=300,
		llm_timeout=180,
		max_failures=5,
		directly_open_url=True,
	)
	print("✅ Agent créé")

	print("▶️  Démarrage de l'exécution de l'agent...")
	history = await agent.run()
	print("✅ Exécution terminée")
	
	# Check if agent completed successfully
	agent_successful = history.is_successful()
	if not agent_successful and history.has_errors():
		print("⚠️  ATTENTION: Il semble y avoir eu un problème avec l'agent, mais on va essayer d'extraire les données quand même.")
	
	# Try to get structured output first
	if history.structured_output:
		return _sanitize_report(history.structured_output)  # type: ignore[arg-type]

	# Try to extract from final result
	final_result = history.final_result()
	if final_result:
		try:
			# Try to parse as JSON
			report = StartupListingReport.model_validate_json(final_result)
			if not agent_successful:
				print("⚠️  Données récupérées depuis le résultat final malgré l'échec de l'agent.")
			return _sanitize_report(report)
		except ValidationError:
			# Try to extract JSON from markdown code blocks
			json_match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', final_result, re.DOTALL)
			if json_match:
				try:
					report = StartupListingReport.model_validate_json(json_match.group(1))
					if not agent_successful:
						print("⚠️  Données récupérées depuis le résultat final (markdown) malgré l'échec de l'agent.")
					return _sanitize_report(report)
				except ValidationError:
					pass

	# Try to extract from action results (especially extract actions)
	extracted_contents = history.extracted_content()
	for content in reversed(extracted_contents):  # Start from most recent
		if not content:
			continue
		try:
			# Try to parse as JSON directly
			report = StartupListingReport.model_validate_json(content)
			if not agent_successful:
				print("⚠️  Données récupérées depuis les résultats d'extraction malgré l'échec de l'agent.")
			return _sanitize_report(report)
		except ValidationError:
			# Try to extract JSON from markdown
			json_match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', content, re.DOTALL)
			if json_match:
				try:
					report = StartupListingReport.model_validate_json(json_match.group(1))
					if not agent_successful:
						print("⚠️  Données récupérées depuis les résultats d'extraction (markdown) malgré l'échec de l'agent.")
					return _sanitize_report(report)
				except ValidationError:
					pass
			# Try to find JSON object in the content
			json_match = re.search(r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})', content, re.DOTALL)
			if json_match:
				try:
					report = StartupListingReport.model_validate_json(json_match.group(1))
					if not agent_successful:
						print("⚠️  Données récupérées depuis les résultats d'extraction (JSON brut) malgré l'échec de l'agent.")
					return _sanitize_report(report)
				except ValidationError:
					pass

	# Try to extract from model actions (look for done actions with data)
	for action_dict in reversed(history.model_actions()):
		if 'done' in action_dict:
			done_data = action_dict.get('done', {})
			if isinstance(done_data, dict) and 'data' in done_data:
				data = done_data['data']
				# Convert AnyHttpUrl to string if needed (deep copy to avoid modifying original)
				data_copy = copy.deepcopy(data) if isinstance(data, dict) else data
				if isinstance(data_copy, dict) and 'source_url' in data_copy:
					source_url = data_copy['source_url']
					# Handle AnyHttpUrl or other URL types
					if hasattr(source_url, '__str__') and not isinstance(source_url, str):
						data_copy['source_url'] = str(source_url)
					# Also handle startups list
					if 'startups' in data_copy and isinstance(data_copy['startups'], list):
						for startup in data_copy['startups']:
							if isinstance(startup, dict):
								# Ensure all URLs are strings
								for url_field in ['listing_url', 'linkedin_url']:
									if url_field in startup and startup[url_field] is not None:
										if hasattr(startup[url_field], '__str__') and not isinstance(startup[url_field], str):
											startup[url_field] = str(startup[url_field])
				try:
					report = StartupListingReport.model_validate(data_copy)
					if not agent_successful:
						print("⚠️  Données récupérées depuis l'action 'done' malgré l'échec de l'agent.")
					return _sanitize_report(report)
				except ValidationError as e:
					# Try with JSON serialization first
					try:
						json_str = json.dumps(data_copy, default=str)
						report = StartupListingReport.model_validate_json(json_str)
						if not agent_successful:
							print("⚠️  Données récupérées depuis l'action 'done' (après conversion JSON) malgré l'échec de l'agent.")
						return _sanitize_report(report)
					except (ValidationError, json.JSONDecodeError):
						pass

	# If we get here, we couldn't extract any data
	if not agent_successful:
		print("❌ Impossible d'extraire les données malgré plusieurs tentatives.")
	return _fallback_report(str(task_input.url), "L'agent a été interrompu avant de finaliser le JSON.")


def parse_arguments() -> StartupListingInput:
	"""Validate CLI arguments via Pydantic before launching the agent."""

	parser = argparse.ArgumentParser(description='Construit un listing de startups depuis une page Product Hunt/BetaList/etc.')
	parser.add_argument('url', help='URL du listing (Product Hunt, BetaList, FutureTools, etc.)')
	parser.add_argument(
		'--max-startups',
		type=int,
		default=12,
		help='Nombre maximal de startups à extraire (par défaut: 12)',
	)
	parser.add_argument(
		'--output',
		default='startup_listings.json',
		help='Chemin du fichier JSON résultat (par défaut: ./startup_listings.json)',
	)
	args = parser.parse_args()
	return StartupListingInput(url=args.url, max_startups=args.max_startups, output_path=Path(args.output))


async def main() -> None:
	"""CLI entry point."""

	try:
		task_input = parse_arguments()
		print(f"🚀 Démarrage de l'agent pour: {task_input.url}")
		print(f"📊 Nombre max de startups: {task_input.max_startups}")
		print(f"💾 Fichier de sortie: {task_input.output_path}")
		
		result = await run_startup_listing(task_input)

		if result is None:
			print("❌ L'agent n'a retourné aucune donnée structurée.")
			return

		output_json = result.model_dump_json(indent=2, ensure_ascii=False)
		output_path = task_input.output_path
		output_path.parent.mkdir(parents=True, exist_ok=True)
		output_path.write_text(output_json, encoding='utf-8')

		print(output_json)
		print(f'\n✅ Listing sauvegardé dans: {output_path.resolve()}')
	except KeyboardInterrupt:
		print("\n⚠️  Interruption utilisateur détectée.")
		raise
	except Exception as e:
		print(f"❌ Erreur lors de l'exécution: {e}")
		import traceback
		traceback.print_exc()
		raise


if __name__ == '__main__':
	asyncio.run(main())
