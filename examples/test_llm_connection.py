"""
Script de test pour vérifier la connexion LLM avec LiteLLM.

Ce script teste simplement si la connexion à votre serveur LiteLLM fonctionne
sans lancer tout l'agent browser-use.
"""

from browser_use import ChatOpenAI
from dotenv import load_dotenv
import asyncio
import httpx
import time
import os
import sys

# Charge les variables d'environnement
load_dotenv()


async def test_network_connectivity():
	"""Teste d'abord la connectivité réseau de base."""
	url = os.getenv('OPENAI_API_URL', '')
	if not url:
		print("❌ OPENAI_API_URL non défini dans .env")
		return False
	
	print("🌐 Test de connectivité réseau...")
	print(f"   URL: {url}")
	
	try:
		# Test simple de connectivité avec un timeout court
		async with httpx.AsyncClient(timeout=10.0) as client:
			# Test avec un endpoint simple (health check si disponible)
			test_url = url.rstrip('/') + '/health' if not url.endswith('/v1') else url.rstrip('/v1') + '/health'
			try:
				response = await client.get(test_url)
				print(f"   ✅ Serveur accessible (status: {response.status_code})")
				return True
			except httpx.TimeoutException:
				print("   ⚠️  Timeout sur /health, mais le serveur peut être accessible")
				return True
			except Exception as e:
				# Si /health n'existe pas, ce n'est pas grave
				print(f"   ℹ️  /health non disponible ({type(e).__name__}), testons directement l'API")
				return True
	except Exception as e:
		print(f"   ❌ Erreur de connectivité: {type(e).__name__}: {str(e)}")
		return False


async def test_llm_connection():
	"""Teste la connexion LLM avec un appel simple."""
	print("\n🔍 Test de connexion LLM...")
	print(f"   URL: {os.getenv('OPENAI_API_URL', 'Non défini')}")
	model_name = "gemini-2.5-flash-lite-preview-09-2025"
	print(f"   Modèle: {model_name}")
	print()
	
	# Test de connectivité d'abord
	if not await test_network_connectivity():
		print("\n❌ Problème de connectivité réseau. Vérifiez:")
		print("   1. Que le serveur LiteLLM est accessible")
		print("   2. Que vous êtes sur le bon réseau/VPN")
		print("   3. Que l'URL est correcte")
		return False
	
	# Créer le client LLM avec timeout raisonnable
	# Note: Le modèle fonctionne (testé avec curl), mais le schéma JSON structuré peut être lent
	llm = ChatOpenAI(
		model=model_name,
		timeout=httpx.Timeout(180.0, connect=30.0),  # 3 minutes (schéma JSON peut être lent)
		# Options de compatibilité Gemini
		add_schema_to_system_prompt=True,
		remove_min_items_from_schema=True,
		remove_defaults_from_schema=True,
	)
	
	# Message de test simple
	test_message = "Réponds simplement 'OK' si tu reçois ce message."
	
	print("📤 Envoi du message de test (timeout: 180s pour schéma JSON)...")
	start_time = time.time()
	
	try:
		# Test simple avec un message
		from browser_use.llm.messages import UserMessage
		messages = [UserMessage(content=test_message)]
		
		# Utiliser asyncio.wait_for pour forcer un timeout
		response = await asyncio.wait_for(
			llm.ainvoke(messages),
			timeout=185.0  # Légèrement plus que le timeout HTTP
		)
		elapsed_time = time.time() - start_time
		
		print(f"\n✅ Connexion réussie!")
		print(f"   Temps de réponse: {elapsed_time:.2f} secondes")
		print(f"   Réponse: {response.completion}")
		print(f"   Tokens utilisés: {response.usage.total_tokens if response.usage else 'N/A'}")
		return True
		
	except asyncio.TimeoutError:
		elapsed_time = time.time() - start_time
		print(f"\n❌ Timeout après {elapsed_time:.2f} secondes")
		print("   Le serveur LiteLLM ne répond pas dans les temps.")
		print("   Vérifiez:")
		print("   1. Que le serveur est en cours d'exécution")
		print("   2. Que le modèle est disponible sur le serveur")
		print("   3. Que vous avez les bonnes permissions")
		return False
		
	except Exception as e:
		elapsed_time = time.time() - start_time
		print(f"\n❌ Erreur de connexion après {elapsed_time:.2f} secondes")
		print(f"   Type d'erreur: {type(e).__name__}")
		print(f"   Message: {str(e)}")
		
		# Suggestions selon le type d'erreur
		if "timeout" in str(e).lower() or "timed out" in str(e).lower():
			print("\n   💡 Suggestions:")
			print("      - Le serveur LiteLLM est peut-être surchargé")
			print("      - Essayez avec un modèle plus rapide")
			print("      - Vérifiez la latence réseau vers le serveur")
		elif "401" in str(e) or "unauthorized" in str(e).lower():
			print("\n   💡 Vérifiez votre OPENAI_API_KEY")
		elif "404" in str(e) or "not found" in str(e).lower():
			print("\n   💡 Vérifiez que l'URL est correcte et que le modèle existe")
		
		return False


if __name__ == "__main__":
	try:
		success = asyncio.run(test_llm_connection())
		sys.exit(0 if success else 1)
	except KeyboardInterrupt:
		print("\n\n⚠️  Test interrompu par l'utilisateur")
		sys.exit(130)

