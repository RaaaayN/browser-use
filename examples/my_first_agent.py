"""
Exemple simple pour lancer votre premier agent avec OpenAI.

Configuration:
1. Créez un fichier .env avec:
   OPENAI_API_KEY=votre_cle_api
   OPENAI_API_URL=https://litellm.internal.syntia.app

2. Ou exportez les variables d'environnement:
   export OPENAI_API_KEY=votre_cle_api
   export OPENAI_API_URL=https://litellm.internal.syntia.app
"""

from browser_use import Agent, ChatOpenAI
from dotenv import load_dotenv
import asyncio

# Charge les variables d'environnement depuis .env
load_dotenv()


async def main():
	# Créer le LLM avec votre URL personnalisée
	# L'URL sera automatiquement lue depuis OPENAI_API_URL si définie
	# Note: Avec LiteLLM, vous pouvez utiliser des modèles Google via l'API OpenAI
	# Configuration spéciale pour Gemini via LiteLLM (compatibilité schéma JSON)
	import httpx
	# Utiliser un modèle disponible sur votre serveur LiteLLM
	# Modèles disponibles: gemini-2.5-flash, gemini-2.5-flash-thinking, gemini-2.5-flash-lite-thinking
	llm = ChatOpenAI(
		model="gemini-2.5-flash-lite-preview-09-2025",  # Modèle qui fonctionne (testé avec curl/httpx)
		# IMPORTANT: Timeouts détaillés - le client OpenAI peut être lent à établir la connexion
		timeout=httpx.Timeout(180.0, connect=60.0, read=180.0, write=30.0),  # 3 min total, 1 min connexion
		max_retries=2,  # Réduire les retries (défaut: 5) pour éviter les timeouts cumulés
		# Options de compatibilité Gemini
		# IMPORTANT: Ne pas ajouter le schéma au prompt car LiteLLM/Gemini le détecte et l'envoie comme response_schema
		# ce qui cause l'erreur 400 avec les objets vides
		add_schema_to_system_prompt=False,  # Désactiver pour éviter que LiteLLM envoie le schéma à Gemini
		remove_min_items_from_schema=True,  # Gemini n'aime pas minItems
		remove_defaults_from_schema=True,  # Gemini n'aime pas les valeurs par défaut avec anyOf
		dont_force_structured_output=True,  # Ne pas forcer le mode structuré (évite response_format)
	)
	
	# Définir la tâche
	task = "Find the number 1 post on Show HN"
	
	# Créer l'agent avec optimisations de vitesse
	# flash_mode désactive le "thinking" et simplifie le prompt pour accélérer les réponses
	agent = Agent(
		task=task, 
		llm=llm,
		flash_mode=True,  # Mode rapide : désactive thinking, evaluation, next_goal (plus rapide)
		llm_timeout=180,  # 3 minutes pour les appels LLM (Gemini via LiteLLM peut être lent)
		step_timeout=240,  # 4 minutes pour chaque étape complète
		use_thinking=False,  # Désactiver le thinking (déjà fait par flash_mode mais explicite)
	)
	
	# Lancer l'agent
	history = await agent.run()
	
	# Afficher le résultat
	print("\n✅ Tâche terminée!")
	print(f"Résultat: {history.final_result()}")


if __name__ == "__main__":
	asyncio.run(main())

