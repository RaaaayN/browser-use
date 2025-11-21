"""
Agent automatique pour imprimer n'importe quelle page en PDF

Ce script :
1. Navigue vers une URL
2. Attend que la page charge complètement
3. Pour les URLs Airtable : utilise "Imprimer la vue" (formatage optimisé)
4. Pour les autres pages : génère un PDF directement via CDP
5. Sauvegarde le PDF automatiquement dans le dossier ./pdfs

Fonctionnalités spéciales pour Airtable :
- Détecte automatiquement les URLs Airtable
- Accepte les cookies si nécessaire
- Déclenche "Imprimer la vue" via JavaScript
- Capture le PDF généré par Airtable (formatage optimisé)

Usage:
    # Utiliser l'URL par défaut
    uv run python examples/use-cases/auto_print_pdf.py
    
    # Passer une URL en argument
    uv run python examples/use-cases/auto_print_pdf.py "https://airtable.com/..."

Pour changer l'URL par défaut, modifiez la variable `url` dans le script.
"""

import asyncio
import base64
import os
import re
import sys
import time
from pathlib import Path

# Add the parent directory to the path so we can import browser_use
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)

from browser_use import Browser


def is_airtable_url(url: str) -> bool:
	"""Vérifie si l'URL est une URL Airtable."""
	return 'airtable.com' in url.lower()


async def trigger_airtable_print_view(browser: Browser) -> bool:
	"""
	Déclenche "Imprimer la vue" sur une page Airtable.
	Ouvre d'abord le menu ellipsis, puis cherche et clique sur "Imprimer la vue".
	
	Returns:
		True si l'action a été déclenchée avec succès
	"""
	try:
		cdp_session = await browser.get_or_create_cdp_session(focus=True)
		
		# Script JavaScript pour ouvrir le menu et déclencher "Imprimer la vue"
		script = '''(function(){
try {
	const allButtons = Array.from(document.querySelectorAll('button, [role="button"], a[role="button"]'));
	
	const cookieButton = allButtons.find(btn => {
		const text = (btn.textContent || '').toLowerCase();
		const ariaLabel = (btn.getAttribute('aria-label') || '').toLowerCase();
		const id = (btn.getAttribute('id') || '').toLowerCase();
		const className = (btn.getAttribute('class') || '').toLowerCase();
		return text.includes('accept') || text.includes('accepter') || 
		       text.includes('agree') || text.includes('ok') ||
		       ariaLabel.includes('accept') || ariaLabel.includes('accepter') ||
		       id.includes('cookie') || className.includes('cookie');
	});
	
	if (cookieButton && cookieButton.offsetParent !== null) {
		try {
			cookieButton.click();
		} catch (e) {}
	}
	
	const allButtons2 = Array.from(document.querySelectorAll('button, [role="button"], a[role="button"]'));
	let ellipsisButton = null;
	
	for (const btn of allButtons2) {
		const parent = btn.closest('[class*="viewBar"], [class*="toolbar"], [class*="header"], [class*="viewControls"], [class*="viewHeader"]');
		if (parent) {
			const parentText = parent.textContent || '';
			if (parentText.includes('Filtrer') || parentText.includes('Trier') || parentText.includes('Filter') || parentText.includes('Sort')) {
				const ariaLabel = (btn.getAttribute('aria-label') || '').toLowerCase();
				const title = (btn.getAttribute('title') || '').toLowerCase();
				const hasMoreOptions = ariaLabel.includes('more') || ariaLabel.includes('options') || title.includes('more') || title.includes('options');
				
				const svg = btn.querySelector('svg');
				const hasEllipsisIcon = svg && (svg.querySelectorAll('path, circle').length >= 3);
				
				const btnText = (btn.textContent || '').trim();
				const isEllipsis = btnText === '...' || btnText === '⋯' || btnText === '⋮';
				
				if (hasMoreOptions || hasEllipsisIcon || isEllipsis) {
					ellipsisButton = btn;
					break;
				}
			}
		}
	}
	
	if (!ellipsisButton) {
		return false;
	}
	
	ellipsisButton.click();
	
	return true;
} catch (e) {
	return false;
}
})()'''
		
		# Ouvrir le menu ellipsis
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': script, 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		
		menu_opened = result.get('result', {}).get('value', False)
		if not menu_opened:
			return False
		
		# Attendre que le menu apparaisse
		await asyncio.sleep(1)
		
		# Script pour trouver et cliquer sur "Imprimer la vue"
		script2 = '''(function(){
try {
	const allMenuItems = Array.from(document.querySelectorAll('[role="menuitem"], [role="option"], button, a, div[role="button"], li, span, div'));
	const printMenuItem = allMenuItems.find(item => {
		const itemText = (item.textContent || '').toLowerCase().trim();
		return (itemText.includes('imprimer') || itemText.includes('print')) && 
		       (itemText.includes('vue') || itemText.includes('view'));
	});
	
	if (!printMenuItem) {
		return false;
	}
	
	let printTriggered = false;
	
	try {
		const onclick = printMenuItem.getAttribute('onclick');
		if (onclick) {
			eval(onclick);
			printTriggered = true;
		}
	} catch (e) {}
	
	if (!printTriggered && printMenuItem.onclick && typeof printMenuItem.onclick === 'function') {
		try {
			printMenuItem.onclick();
			printTriggered = true;
		} catch (e) {}
	}
	
	if (!printTriggered) {
		try {
			const reactKey = Object.keys(printMenuItem).find(key => 
				key.startsWith('__reactFiber') || key.startsWith('__reactInternalInstance')
			);
			
			if (reactKey && printMenuItem[reactKey]) {
				const fiber = printMenuItem[reactKey];
				let currentFiber = fiber;
				for (let i = 0; i < 5 && currentFiber && !printTriggered; i++) {
					try {
						if (currentFiber.memoizedProps && currentFiber.memoizedProps.onClick) {
							currentFiber.memoizedProps.onClick();
							printTriggered = true;
							break;
						}
					} catch (e) {}
					currentFiber = currentFiber.return || currentFiber._debugOwner;
				}
			}
		} catch (e) {}
	}
	
	if (!printTriggered) {
		try {
			const clickEvent = new MouseEvent('click', {
				bubbles: true,
				cancelable: true,
				view: window,
				detail: 1
			});
			printMenuItem.dispatchEvent(clickEvent);
			printTriggered = true;
		} catch (e) {}
	}
	
	return printTriggered;
} catch (e) {
	return false;
}
})()'''
		
		# Chercher et cliquer sur "Imprimer la vue"
		result2 = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': script2, 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		
		success = result2.get('result', {}).get('value', False)
		return bool(success)
		
	except Exception as e:
		print(f"⚠️  Erreur lors du déclenchement de 'Imprimer la vue': {e}")
		import traceback
		traceback.print_exc()
		return False


async def wait_for_pdf_and_save(browser: Browser, output_dir: str, initial_tab_count: int, timeout: int = 30) -> str | None:
	"""
	Attend qu'un PDF soit généré (par Airtable) et le sauvegarde.
	
	Args:
		browser: Instance Browser
		output_dir: Dossier de sortie
		initial_tab_count: Nombre d'onglets au début (pour détecter les nouveaux)
		timeout: Timeout en secondes
		
	Returns:
		Chemin du fichier PDF sauvegardé, ou None
	"""
	start_time = time.time()
	
	output_path = Path(output_dir).expanduser().resolve()
	output_path.mkdir(parents=True, exist_ok=True)
	
	# Attendre que le PDF soit généré dans un nouvel onglet ou téléchargé
	while time.time() - start_time < timeout:
		try:
			# Vérifier les onglets pour trouver un nouveau PDF ou onglet
			tabs = await browser.get_tabs()
			current_tab_count = len(tabs)
			
			# Si un nouvel onglet a été créé, vérifier s'il contient un PDF
			if current_tab_count > initial_tab_count:
				print(f"📄 Nouvel onglet détecté ({current_tab_count} onglets), vérification...")
				
				for tab in tabs:
					tab_url = tab.url or ''
					# Vérifier si c'est un PDF ou une page d'impression Airtable
					if (tab_url.endswith('.pdf') or 
					    'application/pdf' in tab_url.lower() or 
					    'chrome-extension://' in tab_url or
					    'print' in tab_url.lower()):
						
						print(f"📄 PDF/page d'impression détectée: {tab_url[:80]}...")
						
						# Attendre un peu que la page charge
						await asyncio.sleep(2)
						
						# Générer le PDF depuis cet onglet
						try:
							cdp_session = await browser.get_or_create_cdp_session(target_id=tab.target_id, focus=True)
							
							pdf_result = await asyncio.wait_for(
								cdp_session.cdp_client.send.Page.printToPDF(
									params={
										'printBackground': True,
										'preferCSSPageSize': True,
									},
									session_id=cdp_session.session_id,
								),
								timeout=30.0,
							)
							
							pdf_data = pdf_result.get('data')
							if pdf_data:
								pdf_bytes = base64.b64decode(pdf_data)
								
								# Générer nom de fichier
								try:
									page_title = await browser.get_current_page_title()
									safe_title = re.sub(r'[^\w\s-]', '', page_title)[:50]
									filename = f'{safe_title}.pdf' if safe_title else f'airtable_view_{int(time.time())}.pdf'
								except:
									filename = f'airtable_view_{int(time.time())}.pdf'
								
								final_path = output_path / filename
								
								# Générer nom unique si existe
								if final_path.exists():
									base, ext = os.path.splitext(filename)
									counter = 1
									while (output_path / f'{base} ({counter}){ext}').exists():
										counter += 1
									final_path = output_path / f'{base} ({counter}){ext}'
								
								# Sauvegarder
								import anyio
								async with await anyio.open_file(final_path, 'wb') as f:
									await f.write(pdf_bytes)
								
								file_size = final_path.stat().st_size
								print(f"✅ PDF généré avec succès!")
								print(f"   📁 Fichier: {final_path}")
								print(f"   📊 Taille: {file_size:,} octets ({file_size / 1024:.2f} KB)")
								
								return str(final_path)
						except Exception as e:
							print(f"⚠️  Erreur lors de la génération du PDF depuis l'onglet: {e}")
			
			await asyncio.sleep(1)  # Attendre 1 seconde avant de réessayer
			
		except Exception as e:
			print(f"⚠️  Erreur lors de l'attente du PDF: {e}")
			await asyncio.sleep(1)
	
	print("❌ Timeout: PDF non détecté après l'impression")
	print("💡 Astuce: Airtable peut avoir ouvert le PDF dans une nouvelle fenêtre. Vérifiez manuellement.")
	return None


async def generate_pdf_from_page(browser: Browser, url: str, output_dir: str = "./pdfs") -> str | None:
	"""
	Génère un PDF directement depuis la page actuelle via CDP.
	Pour les URLs Airtable, utilise "Imprimer la vue".
	Pour les autres pages, utilise printToPDF générique.
	
	Args:
		browser: Instance Browser
		url: URL de la page à imprimer
		output_dir: Dossier où sauvegarder le PDF
		
	Returns:
		Chemin du fichier PDF créé, ou None en cas d'erreur
	"""
	try:
		# Naviguer vers l'URL
		print(f"🌐 Navigation vers: {url}")
		await browser.navigate_to(url=url, new_tab=False)
		
		# Attendre que la page charge complètement
		print("⏳ Attente du chargement complet de la page...")
		await asyncio.sleep(3)  # Attendre 3 secondes pour le chargement
		
		# Vérifier si c'est une URL Airtable
		if is_airtable_url(url):
			print("🔍 URL Airtable détectée, utilisation de 'Imprimer la vue'...")
			
			# Compter les onglets avant de déclencher l'impression
			initial_tabs = await browser.get_tabs()
			initial_tab_count = len(initial_tabs)
			
			# Déclencher "Imprimer la vue"
			print("🖨️  Déclenchement de 'Imprimer la vue'...")
			success = await trigger_airtable_print_view(browser)
			
			if success:
				print("✅ 'Imprimer la vue' déclenché, attente que la page se prépare...")
				await asyncio.sleep(2)  # Attendre que la page se prépare pour l'impression
				
				# Vérifier d'abord les nouveaux onglets (Airtable peut ouvrir le PDF dans un nouvel onglet)
				tabs = await browser.get_tabs()
				if len(tabs) > initial_tab_count:
					print(f"📄 Nouvel onglet détecté ({len(tabs)} onglets), vérification...")
					for tab in tabs:
						tab_url = tab.url or ''
						if (tab_url.endswith('.pdf') or 
						    'application/pdf' in tab_url.lower() or 
						    'print' in tab_url.lower() or
						    'chrome-extension://' in tab_url):
							print(f"📄 PDF/page d'impression détectée dans l'onglet: {tab_url[:80]}...")
							await asyncio.sleep(2)  # Attendre que la page charge
							try:
								cdp_session_tab = await browser.get_or_create_cdp_session(target_id=tab.target_id, focus=True)
								pdf_result = await cdp_session_tab.cdp_client.send.Page.printToPDF(
									params={'printBackground': True, 'preferCSSPageSize': True},
									session_id=cdp_session_tab.session_id,
								)
								pdf_data = pdf_result.get('data')
								if pdf_data:
									pdf_bytes = base64.b64decode(pdf_data)
									output_path = Path(output_dir).expanduser().resolve()
									output_path.mkdir(parents=True, exist_ok=True)
									try:
										page_title = await browser.get_current_page_title()
										safe_title = re.sub(r'[^\w\s-]', '', page_title)[:50]
										filename = f'{safe_title}.pdf' if safe_title else f'airtable_view_{int(time.time())}.pdf'
									except:
										filename = f'airtable_view_{int(time.time())}.pdf'
									final_path = output_path / filename
									if final_path.exists():
										base, ext = os.path.splitext(filename)
										counter = 1
										while (output_path / f'{base} ({counter}){ext}').exists():
											counter += 1
										final_path = output_path / f'{base} ({counter}){ext}'
									import anyio
									async with await anyio.open_file(final_path, 'wb') as f:
										await f.write(pdf_bytes)
									file_size = final_path.stat().st_size
									print(f"✅ PDF généré avec succès depuis le nouvel onglet!")
									print(f"   📁 Fichier: {final_path}")
									print(f"   📊 Taille: {file_size:,} octets ({file_size / 1024:.2f} KB)")
									return str(final_path)
							except Exception as e:
								print(f"⚠️  Erreur lors de la génération depuis le nouvel onglet: {e}")
				
				# Sinon, générer le PDF de la page actuelle
				# Après avoir cliqué sur "Imprimer la vue", Airtable peut avoir préparé la page pour l'impression
				print("📄 Génération du PDF depuis la page actuelle...")
				try:
					cdp_session = await browser.get_or_create_cdp_session(focus=True)
					pdf_result = await cdp_session.cdp_client.send.Page.printToPDF(
						params={
							'printBackground': True,
							'preferCSSPageSize': True,
						},
						session_id=cdp_session.session_id,
					)
					pdf_data = pdf_result.get('data')
					if pdf_data:
						pdf_bytes = base64.b64decode(pdf_data)
						output_path = Path(output_dir).expanduser().resolve()
						output_path.mkdir(parents=True, exist_ok=True)
						try:
							page_title = await browser.get_current_page_title()
							safe_title = re.sub(r'[^\w\s-]', '', page_title)[:50]
							filename = f'{safe_title}.pdf' if safe_title else f'airtable_view_{int(time.time())}.pdf'
						except:
							filename = f'airtable_view_{int(time.time())}.pdf'
						final_path = output_path / filename
						if final_path.exists():
							base, ext = os.path.splitext(filename)
							counter = 1
							while (output_path / f'{base} ({counter}){ext}').exists():
								counter += 1
							final_path = output_path / f'{base} ({counter}){ext}'
						import anyio
						async with await anyio.open_file(final_path, 'wb') as f:
							await f.write(pdf_bytes)
						file_size = final_path.stat().st_size
						print(f"✅ PDF généré avec succès!")
						print(f"   📁 Fichier: {final_path}")
						print(f"   📊 Taille: {file_size:,} octets ({file_size / 1024:.2f} KB)")
						return str(final_path)
				except Exception as e:
					print(f"❌ Erreur lors de la génération du PDF: {e}")
					import traceback
					traceback.print_exc()
					return None
			else:
				print("⚠️  Impossible de déclencher 'Imprimer la vue', utilisation de la méthode générique...")
				# Fallback vers la méthode générique
		
		# Méthode générique pour toutes les autres pages
		print("📄 Génération du PDF via CDP (méthode générique)...")
		
		# Obtenir la session CDP
		cdp_session = await browser.get_or_create_cdp_session(focus=True)
		
		# Générer le PDF directement via CDP Page.printToPDF
		result = await asyncio.wait_for(
			cdp_session.cdp_client.send.Page.printToPDF(
				params={
					'printBackground': True,  # Inclure les arrière-plans
					'preferCSSPageSize': True,  # Utiliser la taille CSS de la page
					'marginTop': 0,
					'marginBottom': 0,
					'marginLeft': 0,
					'marginRight': 0,
				},
				session_id=cdp_session.session_id,
			),
			timeout=30.0,  # Timeout de 30 secondes pour la génération
		)
		
		pdf_data = result.get('data')
		if not pdf_data:
			print("❌ Erreur: Aucune donnée PDF retournée")
			return None
		
		# Décoder les données base64
		pdf_bytes = base64.b64decode(pdf_data)
		
		# Créer le dossier de sortie s'il n'existe pas
		output_path = Path(output_dir).expanduser().resolve()
		output_path.mkdir(parents=True, exist_ok=True)
		
		# Générer un nom de fichier à partir du titre de la page ou de l'URL
		try:
			page_title = await browser.get_current_page_title()
			# Nettoyer le titre pour en faire un nom de fichier valide
			safe_title = re.sub(r'[^\w\s-]', '', page_title)[:50]  # Max 50 caractères
			filename = f'{safe_title}.pdf' if safe_title else 'page.pdf'
		except Exception:
			# Utiliser l'URL comme nom de fichier
			from urllib.parse import urlparse
			parsed = urlparse(url)
			domain = parsed.netloc.replace('www.', '').replace('.', '_')
			path = parsed.path.strip('/').replace('/', '_')[:30] or 'page'
			filename = f'{domain}_{path}.pdf'
		
		# Générer un nom unique si le fichier existe déjà
		final_path = output_path / filename
		if final_path.exists():
			base, ext = os.path.splitext(filename)
			counter = 1
			while (output_path / f'{base} ({counter}){ext}').exists():
				counter += 1
			final_path = output_path / f'{base} ({counter}){ext}'
		
		# Sauvegarder le PDF
		import anyio
		async with await anyio.open_file(final_path, 'wb') as f:
			await f.write(pdf_bytes)
		
		file_size = final_path.stat().st_size
		print(f"✅ PDF généré avec succès!")
		print(f"   📁 Fichier: {final_path}")
		print(f"   📊 Taille: {file_size:,} octets ({file_size / 1024:.2f} KB)")
		
		return str(final_path)
		
	except asyncio.TimeoutError:
		print("❌ Erreur: Timeout lors de la génération du PDF")
		return None
	except Exception as e:
		print(f"❌ Erreur lors de la génération du PDF: {e}")
		import traceback
		traceback.print_exc()
		return None


async def main():
	# URL à imprimer - MODIFIEZ ICI pour changer la page
	url = "https://airtable.com/appfLUDj8A9RFqyxy/shrGtTkoHk6QOpsrT/tbluZLSM3l4mENfIk?viewControls=on"
	
	# Vous pouvez aussi passer l'URL en argument
	if len(sys.argv) > 1:
		url = sys.argv[1]
	
	print("=" * 60)
	print("🖨️  Agent d'impression PDF automatique")
	print("=" * 60)
	print(f"URL: {url}")
	print()
	
	# Configurer le navigateur
	# headless=True pour ne pas afficher la fenêtre (plus rapide)
	# headless=False pour voir ce qui se passe
	browser = Browser(
		headless=False,  # Changez à True pour masquer la fenêtre
		downloads_path="./pdfs",  # Dossier pour les téléchargements
	)
	
	try:
		# Démarrer le navigateur
		await browser.start()
		
		# Générer le PDF
		pdf_path = await generate_pdf_from_page(browser, url, output_dir="./pdfs")
		
		if pdf_path:
			print()
			print("=" * 60)
			print("✅ Tâche terminée avec succès!")
			print(f"📄 PDF sauvegardé: {pdf_path}")
			print("=" * 60)
		else:
			print()
			print("=" * 60)
			print("❌ Échec de la génération du PDF")
			print("=" * 60)
			
	finally:
		# Fermer le navigateur
		try:
			await browser.stop()
		except Exception as e:
			print(f"⚠️  Erreur lors de la fermeture: {e}")


if __name__ == '__main__':
	asyncio.run(main())

