#!/usr/bin/env python3
"""
Script simple d'extraction de données Airtable.
Utilise juste un lien Airtable partagé.

Utilisation:
    uv run examples/airtable_extract.py "https://airtable.com/appXXX/shrXXX"
"""

import json
import sys
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx
import re


async def get_api_url_from_page(airtable_url: str) -> Optional[str]:
    """
    Utilise Browser-Use pour charger la page et intercepter l'URL de l'API depuis les requêtes réseau CDP.
    """
    try:
        from browser_use import Browser
        
        browser = Browser(headless=True)
        await browser.start()
        
        try:
            # Variables pour stocker l'URL et les headers interceptés
            intercepted_url = None
            intercepted_headers = None
            event_received = asyncio.Event()
            
            # Obtenir le CDP client root
            cdp_client = browser._cdp_client_root
            if not cdp_client:
                return None
            
            # Enregistrer un handler GLOBAL pour les requêtes réseau (avant de créer la page)
            def on_request_sent(event, session_id=None):
                nonlocal intercepted_url, intercepted_headers
                try:
                    request = event.get('request', {})
                    url = request.get('url', '')
                    if url and 'readSharedViewData' in url:
                        intercepted_url = url
                        intercepted_headers = request.get('headers', {})
                        print(f"   ✅ Requête interceptée: {url[:100]}...")
                        if not event_received.is_set():
                            event_received.set()
                except Exception as e:
                    pass
            
            # Enregistrer aussi un handler pour les réponses (au cas où)
            def on_response_received(event, session_id=None):
                nonlocal intercepted_url
                try:
                    response = event.get('response', {})
                    url = response.get('url', '')
                    if url and 'readSharedViewData' in url and not intercepted_url:
                        intercepted_url = url
                        print(f"   ✅ Réponse interceptée: {url[:100]}...")
                        if not event_received.is_set():
                            event_received.set()
                except Exception:
                    pass
            
            # Enregistrer les handlers globalement
            cdp_client.register.Network.requestWillBeSent(on_request_sent)
            cdp_client.register.Network.responseReceived(on_response_received)
            
            # Créer la page (cela va déclencher la navigation)
            page = await browser.new_page(airtable_url)
            
            # Obtenir la session CDP pour cette page et activer Network
            try:
                # Attendre un peu que la page commence à charger
                await asyncio.sleep(1)
                
                # Obtenir tous les targets
                pages = await browser.get_pages()
                if pages:
                    current_page = pages[0]
                    # Obtenir le target_id depuis la page
                    if hasattr(current_page, '_target_id'):
                        target_id = current_page._target_id
                        cdp_session = await browser.get_or_create_cdp_session(target_id, focus=False)
                        if cdp_session and cdp_session.session_id:
                            # Activer Network domain sur cette session
                            await cdp_client.send.Network.enable(session_id=cdp_session.session_id)
            except Exception as e:
                print(f"   ⚠️  Note: {e}")
            
            # Attendre que la page charge et que les requêtes soient faites
            # Attendre jusqu'à 10 secondes pour intercepter la requête
            try:
                await asyncio.wait_for(event_received.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                # Si pas intercepté, attendre encore un peu au cas où
                await asyncio.sleep(3)
            
            if intercepted_url:
                # Retourner l'URL et les headers si disponibles
                return (intercepted_url, intercepted_headers)
            
            return None
            
        finally:
            await browser.stop()
            
    except ImportError:
        return None
    except Exception as e:
        print(f"   ⚠️  Erreur: {e}")
        import traceback
        traceback.print_exc()
        return None


async def get_view_id_from_page(airtable_url: str) -> Optional[str]:
    """
    Utilise Browser-Use pour charger la page et extraire le view_id depuis le DOM JavaScript.
    """
    try:
        from browser_use import Browser
        
        browser = Browser(headless=True)
        await browser.start()
        
        try:
            page = await browser.new_page(airtable_url)
            
            # Attendre que la page charge
            await asyncio.sleep(3)
            
            # Exécuter JavaScript pour extraire le view_id
            js_code = """() => {
                let viewId = null;
                
                // Chercher dans window.__INITIAL_STATE__ ou autres objets
                const searchInObject = (obj, depth = 0) => {
                    if (depth > 3 || viewId) return;
                    if (!obj || typeof obj !== 'object') return;
                    
                    try {
                        for (const key in obj) {
                            if (viewId) break;
                            const value = obj[key];
                            
                            if (key.toLowerCase().includes('view') && typeof value === 'string' && value.startsWith('viw')) {
                                viewId = value;
                                break;
                            }
                            
                            if (typeof value === 'object' && value !== null) {
                                searchInObject(value, depth + 1);
                            }
                        }
                    } catch (e) {}
                };
                
                searchInObject(window);
                
                // Chercher dans les objets d'état
                const stateObjects = ['__INITIAL_STATE__', '__AIRTABLE_INITIAL_STATE__', '__NEXT_DATA__'];
                for (const stateName of stateObjects) {
                    if (window[stateName]) {
                        const state = window[stateName];
                        if (state.view && state.view.id && state.view.id.startsWith('viw')) {
                            viewId = state.view.id;
                            break;
                        }
                        searchInObject(state);
                    }
                }
                
                // Chercher dans l'URL
                if (!viewId) {
                    const urlMatch = window.location.href.match(/\\/view\\/(viw[a-zA-Z0-9]+)/);
                    if (urlMatch) {
                        viewId = urlMatch[1];
                    }
                }
                
                // Chercher dans les scripts
                if (!viewId) {
                    const scripts = Array.from(document.querySelectorAll('script'));
                    for (const script of scripts) {
                        const content = script.textContent || script.innerHTML || '';
                        const match = content.match(/"viewId"\\s*:\\s*"(viw[a-zA-Z0-9]+)"/);
                        if (match) {
                            viewId = match[1];
                            break;
                        }
                    }
                }
                
                return viewId;
            }"""
            
            result = await page.evaluate(js_code)
            
            # Parser le résultat
            view_id = None
            if result:
                try:
                    parsed = json.loads(result)
                    view_id = parsed if isinstance(parsed, str) else None
                except (json.JSONDecodeError, TypeError):
                    view_id = result if isinstance(result, str) and result.startswith('viw') else None
            
            return view_id
            
        finally:
            await browser.stop()
            
    except ImportError:
        # Fallback: essayer avec HTTP simple
        try:
            page_response = httpx.get(airtable_url, timeout=15.0, follow_redirects=True)
            page_content = page_response.text
            
            patterns = [
                r'"viewId"\s*:\s*"(viw[a-zA-Z0-9]+)"',
                r'/view/(viw[a-zA-Z0-9]+)',
                r'data-view-id=["\'](viw[a-zA-Z0-9]+)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, page_content)
                if match:
                    view_id = match.group(1) if match.lastindex else match.group(0)
                    if view_id.startswith('viw'):
                        return view_id
        except:
            pass
        
        return None
    except Exception as e:
        print(f"   ⚠️  Erreur: {e}")
        return None


def extract_airtable_data(airtable_url: str) -> Dict[str, Any]:
    """
    Extrait les données depuis un lien Airtable partagé.
    
    Args:
        airtable_url: URL de la vue partagée Airtable
    
    Returns:
        Données JSON structurées
    """
    import re
    import urllib.parse
    import time
    
    # Si c'est déjà une URL API complète, l'utiliser directement
    if "/v0.3/view/" in airtable_url or "/readSharedViewData" in airtable_url:
        api_url = airtable_url
    else:
        # Extraire les IDs depuis l'URL partagée
        app_match = re.search(r'/app([a-zA-Z0-9]+)', airtable_url)
        shr_match = re.search(r'/shr([a-zA-Z0-9]+)', airtable_url)
        
        app_id = app_match.group(1) if app_match else None
        share_id = shr_match.group(1) if shr_match else None
        
        if not app_id or not share_id:
            print("❌ Impossible d'extraire app_id et share_id de l'URL")
            print("   Format attendu: https://airtable.com/appXXX/shrXXX")
            sys.exit(1)
        
        print(f"   Extraction des IDs: app={app_id}, share={share_id}")
        print("   Récupération de l'URL API depuis les requêtes réseau...")
        
        # Utiliser Browser-Use pour intercepter l'URL de l'API directement depuis les requêtes réseau
        result = asyncio.run(get_api_url_from_page(airtable_url))
        
        intercepted_headers = None
        if result:
            if isinstance(result, tuple):
                api_url, intercepted_headers = result
                # Utiliser les headers interceptés si disponibles
                if intercepted_headers:
                    print("   ✅ Headers interceptés, utilisation pour la requête")
            else:
                api_url = result
        else:
            api_url = None
        
        if not api_url:
            print("   ⚠️  URL API non interceptée depuis les requêtes réseau")
            print("\n   💡 Pour obtenir l'URL complète de l'API:")
            print("      1. Ouvrez la page Airtable dans votre navigateur")
            print("      2. Ouvrez les DevTools (F12)")
            print("      3. Allez dans l'onglet 'Network'")
            print("      4. Rechargez la page (F5)")
            print("      5. Cherchez une requête nommée 'readSharedViewData'")
            print("      6. Copiez l'URL complète de cette requête")
            print("\n   Exemple d'URL API:")
            print("      https://airtable.com/v0.3/view/viwXXX/readSharedViewData?...")
            sys.exit(1)
    
    # Headers pour la requête
    # Si on a intercepté des headers, les utiliser, sinon utiliser des headers par défaut
    if intercepted_headers:
        headers = intercepted_headers.copy()
        # S'assurer que certains headers essentiels sont présents
        if 'accept' not in headers:
            headers['accept'] = '*/*'
        if 'user-agent' not in headers:
            headers['user-agent'] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    else:
        headers = {
            "accept": "*/*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            "x-airtable-accept-msgpack": "true",
            "x-requested-with": "XMLHttpRequest",
        }
    
    print(f"🌐 Récupération des données depuis Airtable...")
    
    try:
        response = httpx.get(api_url, headers=headers, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        
        # Détecter le type de contenu
        content_type = response.headers.get("content-type", "")
        
        if "application/json" in content_type:
            data = response.json()
        elif "application/msgpack" in content_type:
            try:
                import msgpack
                data = msgpack.unpackb(response.content, raw=False)
            except ImportError:
                print("❌ Réponse en msgpack mais module msgpack non installé")
                print("   Installation: uv pip install msgpack")
                sys.exit(1)
            except Exception as e:
                print(f"❌ Erreur lors du décodage msgpack: {e}")
                sys.exit(1)
        else:
            data = response.json()
        
        print(f"   ✅ Données récupérées")
        return data
        
    except httpx.HTTPStatusError as e:
        print(f"❌ Erreur HTTP {e.response.status_code}")
        if e.response.status_code == 401:
            print("   ⚠️  Authentification requise. La vue peut être privée.")
        elif e.response.status_code == 404:
            print("   ⚠️  Vue non trouvée. Vérifiez l'URL.")
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"❌ Erreur de requête: {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Erreur de décodage JSON: {e}")
        sys.exit(1)


def extract_columns(data: Dict[str, Any]) -> Dict[str, str]:
    """Extrait les colonnes et crée un mapping ID -> nom."""
    columns = {}
    table = data.get("data", {}).get("table", {})
    
    for col in table.get("columns", []):
        col_id = col.get("id")
        col_name = col.get("name")
        if col_id and col_name:
            columns[col_id] = col_name
    
    return columns


def process_cell_value(value: Any, col_id: str, data: Dict[str, Any]) -> Any:
    """Traite une valeur de cellule selon son type."""
    if value is None:
        return None
    
    if isinstance(value, list):
        if not value:
            return None
        
        first_item = value[0]
        
        # Attachments
        if isinstance(first_item, dict) and "url" in first_item:
            urls = [item.get("url") for item in value if item.get("url")]
            return urls[0] if len(urls) == 1 else urls
        
        # Foreign keys
        if isinstance(first_item, dict) and "foreignRowId" in first_item:
            display_names = [
                item.get("foreignRowDisplayName")
                for item in value
                if isinstance(item, dict) and item.get("foreignRowDisplayName")
            ]
            return display_names[0] if len(display_names) == 1 else display_names
        
        # Multi-select
        if isinstance(first_item, str) and first_item.startswith("sel"):
            return resolve_select_choices(value, col_id, data)
        
        # Liste de strings
        if isinstance(first_item, str):
            return value[0] if len(value) == 1 else value
    
    return value


def resolve_select_choices(choice_ids: List[str], col_id: str, data: Dict[str, Any]) -> Any:
    """Résout les IDs de choix vers leurs noms."""
    table = data.get("data", {}).get("table", {})
    
    for col in table.get("columns", []):
        if col.get("id") == col_id:
            type_options = col.get("typeOptions", {})
            choices = type_options.get("choices", {})
            
            resolved = []
            for choice_id in choice_ids:
                choice = choices.get(choice_id)
                if choice:
                    resolved.append(choice.get("name"))
                else:
                    resolved.append(choice_id)
            
            return resolved[0] if len(resolved) == 1 else resolved
    
    return choice_ids[0] if len(choice_ids) == 1 else choice_ids


def extract_rows(data: Dict[str, Any], columns: Dict[str, str]) -> List[Dict[str, Any]]:
    """Extrait les lignes et mappe les valeurs aux noms de colonnes."""
    rows = []
    table = data.get("data", {}).get("table", {})
    
    for row in table.get("rows", []):
        row_data = {
            "id": row.get("id"),
            "createdTime": row.get("createdTime"),
        }
        
        cell_values = row.get("cellValuesByColumnId", {})
        
        for col_id, value in cell_values.items():
            col_name = columns.get(col_id)
            if col_name:
                processed_value = process_cell_value(value, col_id, data)
                if processed_value is not None:
                    row_data[col_name] = processed_value
        
        rows.append(row_data)
    
    return rows


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run examples/airtable_extract.py <URL_AIRTABLE>")
        print("\nFormats acceptés:")
        print("  1. URL complète de l'API (recommandé):")
        print('     https://airtable.com/v0.3/view/viwXXX/readSharedViewData?...')
        print("\n  2. URL partagée (le script essaiera de récupérer le view_id):")
        print('     https://airtable.com/appXXX/shrXXX')
        print("\n  Pour obtenir l'URL API complète:")
        print("  - Ouvrez la page dans votre navigateur")
        print("  - DevTools (F12) > Network > Rechargez la page")
        print("  - Cherchez 'readSharedViewData' et copiez l'URL")
        sys.exit(1)
    
    airtable_url = sys.argv[1]
    output_file = "airtable_extracted.json"
    
    # Récupérer les données
    data = extract_airtable_data(airtable_url)
    
    # Vérifier que c'est une réponse valide
    if data.get("msg") != "SUCCESS":
        print(f"⚠️  Avertissement: msg = {data.get('msg')}")
    
    # Extraire les colonnes
    print("\n📋 Extraction des colonnes...")
    columns = extract_columns(data)
    print(f"   ✅ {len(columns)} colonnes trouvées")
    
    # Extraire les lignes
    print("📊 Extraction des lignes...")
    rows = extract_rows(data, columns)
    print(f"   ✅ {len(rows)} lignes extraites")
    
    # Statistiques
    print("\n📈 Statistiques:")
    important_fields = ["Company name", "Website", "Description EN", "Current Program", "Batch"]
    for field in important_fields:
        count = sum(1 for row in rows if row.get(field))
        if count > 0:
            print(f"   - {field}: {count} lignes")
    
    # Préparer le résultat
    result = {
        "metadata": {
            "source": airtable_url,
            "total_columns": len(columns),
            "total_rows": len(rows),
        },
        "columns": [
            {"id": col_id, "name": col_name}
            for col_id, col_name in columns.items()
        ],
        "rows": rows,
    }
    
    # Sauvegarder
    print(f"\n💾 Sauvegarde dans {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    file_size = Path(output_file).stat().st_size / 1024
    print(f"   ✅ Fichier sauvegardé ({file_size:.1f} KB)")
    print(f"\n{'='*70}")
    print("✅ Extraction terminée avec succès!")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
