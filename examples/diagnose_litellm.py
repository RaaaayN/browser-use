"""
Script de diagnostic pour LiteLLM.

Vérifie la connectivité réseau et les problèmes potentiels.
"""

import asyncio
import os
import sys

import httpx
from dotenv import load_dotenv

from browser_use.llm.openai.utils import normalize_openai_base_url

load_dotenv()


async def diagnose():
	"""Diagnostic complet de la connexion LiteLLM."""
	url = os.getenv('OPENAI_API_URL', '')
	normalized_url = normalize_openai_base_url(url)
	api_key = os.getenv('OPENAI_API_KEY', '')
	
	print("🔍 Diagnostic de connexion LiteLLM\n")
	print(f"URL: {url}")
	if normalized_url and normalized_url != url:
		print(f"URL normalisée: {normalized_url}")
	print(f"API Key: {'✅ Définie' if api_key else '❌ Non définie'}")
	print()
	
	if not url:
		print("❌ OPENAI_API_URL non défini")
		return
	
	# Test 1: Connectivité réseau de base
	print("1️⃣  Test de connectivité réseau...")
	try:
		async with httpx.AsyncClient(timeout=5.0) as client:
			# Essayer juste de se connecter
			response = await client.get(url, follow_redirects=True)
			print(f"   ✅ Serveur accessible (HTTP {response.status_code})")
	except httpx.TimeoutException:
		print("   ❌ Timeout - Le serveur ne répond pas")
		print("   💡 Vérifiez:")
		print("      - Que vous êtes sur le bon réseau/VPN")
		print("      - Que le serveur LiteLLM est en cours d'exécution")
		print("      - Que l'URL est correcte")
		return
	except Exception as e:
		print(f"   ⚠️  Erreur: {type(e).__name__}: {str(e)}")
	
	# Test 2: Endpoint /health si disponible
	print("\n2️⃣  Test de l'endpoint /health...")
	try:
		health_url = url.rstrip('/') + '/health'
		async with httpx.AsyncClient(timeout=5.0) as client:
			response = await client.get(health_url)
			print(f"   ✅ Health check OK (HTTP {response.status_code})")
	except Exception as e:
		print(f"   ℹ️  /health non disponible ({type(e).__name__})")
	
	# Test 3: Endpoint /v1/models
	print("\n3️⃣  Test de l'endpoint /v1/models...")
	try:
		api_base = normalized_url or (url.rstrip('/') + '/v1')
		models_url = api_base.rstrip('/') + '/models'
		async with httpx.AsyncClient(timeout=10.0) as client:
			headers = {}
			if api_key:
				headers['Authorization'] = f'Bearer {api_key}'
			response = await client.get(models_url, headers=headers)
			if response.status_code == 200:
				print(f"   ✅ Liste des modèles accessible")
				try:
					data = response.json()
					models = data.get('data', [])
					print(f"   📋 {len(models)} modèle(s) disponible(s)")
					if models:
						print("   Modèles:")
						for model in models[:5]:  # Afficher les 5 premiers
							model_id = model.get('id', 'N/A')
							print(f"      - {model_id}")
				except:
					pass
			else:
				print(f"   ⚠️  HTTP {response.status_code}: {response.text[:100]}")
	except httpx.TimeoutException:
		print("   ❌ Timeout - Le serveur ne répond pas aux requêtes API")
		print("   💡 Le serveur est accessible mais ne répond pas aux requêtes.")
		print("      Cela peut indiquer:")
		print("      - Un problème de configuration du serveur LiteLLM")
		print("      - Un problème de routage réseau")
		print("      - Le serveur est surchargé")
	except Exception as e:
		print(f"   ❌ Erreur: {type(e).__name__}: {str(e)}")
	
	# Test 4: Test d'un appel simple
	print("\n4️⃣  Test d'un appel chat simple...")
	if not api_key:
		print("   ⚠️  API key manquante, test ignoré")
	else:
		try:
			api_base = normalized_url or (url.rstrip('/') + '/v1')
			chat_url = api_base.rstrip('/') + '/chat/completions'
			async with httpx.AsyncClient(timeout=30.0) as client:
				headers = {
					'Authorization': f'Bearer {api_key}',
					'Content-Type': 'application/json',
				}
				payload = {
					'model': 'gemini-2.5-flash-lite-preview-09-2025',
					'messages': [{'role': 'user', 'content': 'Test'}],
					'max_tokens': 10,
				}
				response = await client.post(chat_url, json=payload, headers=headers)
				if response.status_code == 200:
					print("   ✅ Appel chat réussi!")
				else:
					print(f"   ⚠️  HTTP {response.status_code}")
					print(f"   Réponse: {response.text[:200]}")
		except httpx.TimeoutException:
			print("   ❌ Timeout - Le serveur ne répond pas aux appels chat")
			print("   💡 Le modèle peut être très lent ou le serveur surchargé")
		except Exception as e:
			print(f"   ❌ Erreur: {type(e).__name__}: {str(e)}")
	
	print("\n" + "="*50)
	print("💡 Recommandations:")
	print("   1. Vérifiez avec l'équipe qui gère le serveur LiteLLM")
	print("   2. Testez avec un modèle plus rapide (sans 'thinking')")
	print("   3. Vérifiez les logs du serveur LiteLLM")
	print("   4. Essayez depuis un autre réseau pour isoler le problème")


if __name__ == "__main__":
	asyncio.run(diagnose())
