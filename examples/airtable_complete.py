"""
Script complet pour scraper, organiser et extraire les données Airtable.

Ce script fait tout en une seule exécution:
1. Scrape les données depuis une table Airtable partagée (format msgpack)
2. Parse et organise les données (colonnes, lignes)
3. Extrait les valeurs réelles en filtrant les métadonnées
4. Fusionne les lignes avec le même ID
5. Lie les données associées (Batch, Current Program, etc.)
6. Sauvegarde dans un fichier JSON structuré

Fonctionnalités:
- Détection automatique des colonnes (fld...)
- Extraction intelligente des valeurs (filtrage des métadonnées, URLs Airtable, etc.)
- Fusion des lignes dupliquées avec le même ID
- Liaison automatique des Batch aux lignes correspondantes via Current Program
- Mapping intelligent des valeurs (Website, Company Name, Description, etc.)

Usage:
    uv run examples/airtable_complete.py [URL_AIRTABLE] [--output OUTPUT_FILE]
    
Ou avec cookie pour les tables privées:
    AIRTABLE_COOKIE="your_cookie" uv run examples/airtable_complete.py [URL_AIRTABLE]
    
Exemples:
    # Utiliser l'URL par défaut
    uv run examples/airtable_complete.py
    
    # Spécifier une URL et un fichier de sortie
    uv run examples/airtable_complete.py "https://airtable.com/appXXX/shrXXX" --output data.json
    
    # Avec authentification
    AIRTABLE_COOKIE="session=..." uv run examples/airtable_complete.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

# Add the parent directory to the path so we can import browser_use
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from dotenv import load_dotenv

env_path = Path(project_root) / '.env'
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

try:
    import msgpack
except Exception:
    msgpack = None


# ============================================================================
# PARTIE 1: SCRAPING (récupération des données)
# ============================================================================

class AirtableRequestConfig(BaseModel):
    """Configuration pour la requête Airtable."""
    base_url: str = "https://airtable.com/v0.3/view"
    view_id: str = "viw2BuXqXMTdAlSy8"
    share_id: str = "shrGtTkoHk6QOpsrT"
    application_id: str = "appfLUDj8A9RFqyxy"
    generation_number: int = 0
    expires: str = "2025-12-18T00:00:00.000Z"
    signature: str = "703b558f470297c2c349725d8eaf5b45e6fa8db7a4e539a36bb18f3c6fba2f97"
    should_use_nested_response_format: bool = True
    allow_msgpack_of_result: bool = True

    def build_access_policy(self) -> Dict[str, Any]:
        return {
            "allowedActions": [
                {"modelClassName": "view", "modelIdSelector": self.view_id, "action": "readSharedViewData"},
                {"modelClassName": "view", "modelIdSelector": self.view_id, "action": "getMetadataForPrinting"},
                {"modelClassName": "view", "modelIdSelector": self.view_id, "action": "readSignedAttachmentUrls"},
                {
                    "modelClassName": "row",
                    "modelIdSelector": f"rows *[displayedInView={self.view_id}]",
                    "action": "createDocumentPreviewSession",
                },
            ],
            "shareId": self.share_id,
            "applicationId": self.application_id,
            "generationNumber": self.generation_number,
            "expires": self.expires,
            "signature": self.signature,
        }

    def build_stringified_object_params(self) -> str:
        payload = {"shouldUseNestedResponseFormat": self.should_use_nested_response_format}
        if self.allow_msgpack_of_result:
            payload["allowMsgpackOfResult"] = True
        return json.dumps(payload, separators=(",", ":"))

    def build_query_params(self) -> Dict[str, str]:
        return {
            "stringifiedObjectParams": self.build_stringified_object_params(),
            "requestId": f"req{os.urandom(8).hex()[:16]}",
            "accessPolicy": json.dumps(self.build_access_policy(), separators=(",", ":")),
        }

    def build_url(self) -> str:
        query = httpx.QueryParams(self.build_query_params())
        return f"{self.base_url}/{self.view_id}/readSharedViewData?{query}"


def build_headers(config: AirtableRequestConfig, cookie: Optional[str]) -> Dict[str, str]:
    """Construit les headers pour la requête."""
    headers = {
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        "x-airtable-application-id": config.application_id,
        "x-airtable-inter-service-client": "webClient",
        "x-airtable-page-load-id": "pglUhkf9b90Qk7b4l",
        "x-requested-with": "XMLHttpRequest",
        "x-time-zone": "Europe/Paris",
        "x-user-locale": "fr-FR",
    }
    if config.allow_msgpack_of_result:
        headers["x-airtable-accept-msgpack"] = "true"
    if cookie:
        headers["cookie"] = cookie
    return headers


def json_serialize(obj: Any) -> Any:
    """Helper pour sérialiser les objets non-JSON (bytes, etc.)."""
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, dict):
        return {k: json_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_serialize(item) for item in obj]
    return obj


def decode_response(response: httpx.Response) -> Dict[str, Any]:
    """Décode la réponse (JSON ou msgpack)."""
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            return response.json()
        except Exception as e:
            return {"error": f"Failed to decode JSON: {e}", "raw_bytes": response.content.hex()}
    if "application/msgpack" in content_type and msgpack:
        try:
            try:
                return msgpack.unpackb(response.content, raw=False, strict_map_key=False)
            except msgpack.exceptions.ExtraData:
                unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
                unpacker.feed(response.content)
                results = []
                try:
                    while True:
                        results.append(unpacker.unpack())
                except msgpack.exceptions.OutOfData:
                    pass
                if results:
                    if len(results) == 1:
                        return results[0]
                    elif all(isinstance(r, dict) for r in results):
                        combined = {}
                        for r in results:
                            combined.update(r)
                        return combined
                    else:
                        return {"items": results}
                raise ValueError("No valid msgpack data found")
        except Exception as e:
            try:
                return response.json()
            except Exception:
                return {"error": f"Failed to decode msgpack: {e}", "raw_bytes": response.content.hex()[:1000]}
    try:
        return response.json()
    except Exception:
        return {"raw_bytes": response.content.hex(), "content_type": content_type}


def fetch_airtable_data(config: AirtableRequestConfig, cookie: Optional[str]) -> Dict[str, Any]:
    """Récupère les données depuis Airtable."""
    url = config.build_url()
    headers = build_headers(config, cookie)
    
    with httpx.Client(http2=False, headers=headers, follow_redirects=True) as client:
        response = client.get(url, timeout=30.0)
        response.raise_for_status()
        payload = decode_response(response)
        return {
            "url": url,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "payload": payload,
        }


# ============================================================================
# PARTIE 2: EXTRACTION ET ORGANISATION
# ============================================================================

def extract_columns_direct(items: List[Any]) -> List[Dict[str, Any]]:
    """Extrait les colonnes en cherchant directement les patterns fld + nom + type."""
    columns = []
    i = 0
    
    while i < len(items):
        item = items[i]
        
        if isinstance(item, str) and item.startswith("fld"):
            fld_id = item
            col_data = {"id": fld_id}
            
            if i + 1 < len(items):
                next_item = items[i + 1]
                if isinstance(next_item, str) and not next_item.startswith(("fld", "rec", "tbl", "viw", "sel", "usr")):
                    col_data["name"] = next_item
                elif next_item is None:
                    if i + 2 < len(items) and isinstance(items[i + 2], str):
                        col_data["name"] = items[i + 2]
            
            # Types Airtable courants
            airtable_types = [
                "singleLineText", "multilineText", "email", "url", "phoneNumber",
                "number", "percent", "currency", "duration", "rating", "checkbox",
                "date", "dateTime", "multipleAttachments", "multipleRecordLinks",
                "singleSelect", "multipleSelects", "formula", "rollup", "count",
                "multipleAttachment", "foreignKey", "autoNumber", "barcode", "button",
                "createdTime", "lastModifiedTime", "createdBy", "lastModifiedBy",
            ]
            
            for j in range(i + 1, min(i + 10, len(items))):
                potential_type = items[j]
                if isinstance(potential_type, str) and potential_type in airtable_types:
                    col_data["type"] = potential_type
                    break
            
            if "name" in col_data or "type" in col_data:
                columns.append(col_data)
        
        i += 1
    
    return columns


def clean_value(value: Any) -> Any:
    """Nettoie une valeur pour la sérialisation JSON."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {k: clean_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_value(item) for item in value]
    return value


def is_value_item(item: Any) -> bool:
    """Détermine si un item est une valeur de cellule (pas un ID ou métadonnée)."""
    if item is None:
        return False
    if isinstance(item, str):
        # Ignorer les IDs
        if item.startswith(("rec", "fld", "tbl", "viw", "sel", "usr", "att")):
            return False
        # Ignorer les codes courts
        if len(item) < 3:
            return False
        return True
    if isinstance(item, (int, float, bool)):
        # Ignorer les codes/metadonnées (petits entiers)
        if isinstance(item, int) and item < 200:
            return False
        return True
    if isinstance(item, list):
        # Garder les listes avec des strings (sélections multiples)
        return any(isinstance(x, str) and not x.startswith(("rec", "fld")) for x in item)
    return False


def is_metadata_value(value: Any) -> bool:
    """Détermine si une valeur est une métadonnée à ignorer (noms de fichiers, types MIME, dimensions, etc.)."""
    if not isinstance(value, str):
        return False
    
    # Types MIME
    if value.startswith("image/") or value.startswith("application/"):
        return True
    
    # Noms de fichiers avec extensions communes
    if any(value.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".svg", ".gif", ".pdf", ".webp"]):
        # Mais pas si c'est une URL complète
        if not value.startswith("http"):
            return True
    
    # URLs de thumbnails Airtable
    if "airtable.com" in value and ("thumbnail" in value.lower() or "/.euc1/" in value):
        return True
    
    # Petits nombres (probablement des dimensions ou codes)
    if isinstance(value, (int, float)) and not isinstance(value, str) and value < 10000:
        return False  # On garde les nombres pour l'instant
    
    return False


def extract_rows_with_values(items: List[Any], columns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extrait les lignes avec leurs valeurs réelles en analysant la structure sérialisée.
    
    Pattern observé dans les données:
    - rec... (ID de ligne)
    - Industries (avec emoji) - Macro-Industries - Market
    - URL (Website) - si pas Airtable
    - [95] (code attachement)
    - att... (ID attachement)
    - URL logo (Company logo)
    - Nom fichier (à ignorer)
    - "image/png" (type MIME - à ignorer)
    - Nombre (taille - à ignorer)
    - URLs thumbnails (à ignorer)
    - Nombres (dimensions - à ignorer)
    - [94] (code référence)
    - rec... (ID référence Current Program)
    - "Incubateur..." (Current Program)
    - [94] (code référence)
    - rec... (ID référence Batch)
    - "[Batch]..." (Batch)
    - [94] (code référence)
    - rec... (ID référence Industries Product)
    - Industries (avec emoji) - Macro-Industries - Product
    - Description (long texte)
    - Company Name (court texte)
    - 92 (code)
    - rec... (ID ligne suivante ou référence)
    - createdTime (date ISO)
    - 93 (code)
    - [sel...] (sélection)
    """
    rows = []
    
    # Trouver toutes les positions des lignes principales (rec... qui sont des IDs de lignes)
    # On identifie les lignes principales en cherchant des patterns spécifiques
    row_positions = []
    i = 0
    while i < len(items):
        item = items[i]
        
        # Un ID de ligne principal est suivi généralement par des Industries (avec emoji)
        if isinstance(item, str) and item.startswith("rec") and len(item) > 10:
            # Vérifier si c'est suivi d'une valeur intéressante (pas juste une référence)
            # Regarder les 5 prochains items
            is_main_row = False
            for j in range(i + 1, min(i + 6, len(items))):
                next_item = items[j]
                # Si on trouve une Industries avec emoji, une URL, ou une description, c'est une ligne principale
                if isinstance(next_item, str):
                    # Industries avec emoji
                    if len(next_item) > 5 and any(ord(c) > 127 for c in next_item[:5]):
                        is_main_row = True
                        break
                    # URL (pas Airtable)
                    if next_item.startswith("http") and "airtable.com" not in next_item:
                        is_main_row = True
                        break
                    # Description longue
                    if len(next_item) > 50 and not next_item.startswith("http"):
                        is_main_row = True
                        break
            
            if is_main_row:
                row_positions.append(i)
        
        i += 1
    
    # Pour chaque ligne principale, extraire les valeurs
    for idx, pos in enumerate(row_positions):
        row_id = items[pos]
        row_data = {"id": row_id}
        
        # Trouver la position de la prochaine ligne principale
        next_pos = row_positions[idx + 1] if idx + 1 < len(row_positions) else min(pos + 100, len(items))
        
        # Extraire les valeurs mais s'arrêter quand on détecte une nouvelle entreprise
        values = []
        i = pos + 1
        found_company_name = False
        found_description = False
        found_website = False
        found_created_time = False
        
        while i < next_pos:
            item = items[i]
            
            # Détecter les patterns de fin de bloc [0, "00"] - marqueur de fin d'entreprise
            # Vérifier AVANT d'extraire les valeurs pour éviter de mélanger les entreprises
            if isinstance(item, list) and len(item) == 2 and item[0] == 0 and item[1] == "00":
                # Si on a déjà extrait les données principales, vérifier s'il y a une nouvelle entreprise après
                if found_company_name or found_description or found_website:
                    # Vérifier les 5 prochains items pour voir s'il y a une nouvelle entreprise
                    has_new_company = False
                    for j in range(i + 1, min(i + 6, len(items))):
                        next_item = items[j]
                        # Ignorer les codes et métadonnées
                        if isinstance(next_item, int) and next_item < 200:
                            continue
                        if isinstance(next_item, list):
                            continue
                        if isinstance(next_item, str):
                            # URL (pas Airtable) = nouvelle entreprise
                            if next_item.startswith("http") and "airtable.com" not in next_item:
                                has_new_company = True
                                break
                            if next_item.startswith("www."):
                                has_new_company = True
                                break
                            # Description longue = nouvelle entreprise
                            if len(next_item) > 50 and not next_item.startswith("http"):
                                has_new_company = True
                                break
                            # Nom d'entreprise court = nouvelle entreprise
                            if 3 < len(next_item) < 60 and not any(ord(c) > 127 for c in next_item[:3]):
                                if not next_item.startswith("http") and ";" not in next_item:
                                    has_new_company = True
                                    break
                    
                    # Si on a trouvé une nouvelle entreprise après [0, "00"], s'arrêter IMMÉDIATEMENT
                    # Le pattern [0, "00"] marque la fin de l'entreprise actuelle
                    # Ne pas extraire les valeurs qui suivent
                    if has_new_company:
                        # S'arrêter ici, ne pas continuer l'extraction
                        break
                    # Si on a trouvé createdTime, on peut aussi s'arrêter après [0, "00"]
                    elif found_created_time:
                        break
                # Si on a détecté [0, "00"], continuer sans extraire cette valeur
                i += 1
                continue
            
            # Ignorer les codes/metadonnées
            if isinstance(item, int) and item < 200:
                i += 1
                continue
            
            # Ignorer les listes de références simples [94], [95]
            if isinstance(item, list) and len(item) == 1 and isinstance(item[0], int):
                i += 1
                continue
            
            # Détecter si on a trouvé une nouvelle entreprise (pattern: rec... suivi d'Industries/URL/Description)
            if isinstance(item, str) and item.startswith("rec") and len(item) > 10:
                # Vérifier si c'est le début d'une nouvelle entreprise
                # Regarder les 3 prochains items pour voir si c'est un pattern d'entreprise
                is_new_company = False
                for j in range(i + 1, min(i + 4, len(items))):
                    next_item = items[j]
                    if isinstance(next_item, str):
                        # Industries avec emoji
                        if len(next_item) > 5 and any(ord(c) > 127 for c in next_item[:5]) and ";" in next_item:
                            is_new_company = True
                            break
                        # URL (pas Airtable)
                        if next_item.startswith("http") and "airtable.com" not in next_item:
                            is_new_company = True
                            break
                        if next_item.startswith("www."):
                            is_new_company = True
                            break
                        # Description longue
                        if len(next_item) > 50 and not next_item.startswith("http"):
                            is_new_company = True
                            break
                
                # Si c'est une nouvelle entreprise et qu'on a déjà extrait les données principales, s'arrêter
                if is_new_company and (found_company_name or found_description or found_website):
                    break
            
            # Ignorer les IDs de références (rec, att, sel, etc.) sauf si on les utilise
            if isinstance(item, str):
                if item.startswith(("rec", "att", "sel", "fld", "tbl", "viw", "usr")) and len(item) > 10:
                    # On garde les rec... qui peuvent être des références à d'autres tables
                    # Mais on va les utiliser pour mapper les valeurs suivantes
                    pass
                elif not is_metadata_value(item):
                    # AVANT d'extraire, vérifier si on vient de passer un [0, "00"] et si c'est une nouvelle entreprise
                    # Vérifier les 3 items précédents pour voir s'il y a un [0, "00"]
                    just_after_end_marker = False
                    for k in range(max(0, i - 3), i):
                        prev_item = items[k]
                        if isinstance(prev_item, list) and len(prev_item) == 2 and prev_item[0] == 0 and prev_item[1] == "00":
                            # On vient de passer un [0, "00"], vérifier si cette valeur est une nouvelle entreprise
                            if isinstance(item, str):
                                if (item.startswith("www.") or 
                                    (item.startswith("http") and "airtable.com" not in item) or
                                    (len(item) > 50 and not item.startswith("http")) or
                                    (3 < len(item) < 60 and not any(ord(c) > 127 for c in item[:3]) and ";" not in item)):
                                    # C'est probablement une nouvelle entreprise, ne pas l'extraire
                                    just_after_end_marker = True
                                    break
                    
                    if just_after_end_marker:
                        # Ne pas extraire cette valeur, c'est une nouvelle entreprise
                        i += 1
                        continue
                    
                    # C'est une valeur intéressante
                    cleaned = clean_value(item)
                    if cleaned and isinstance(cleaned, str) and cleaned.strip():
                        values.append((i, cleaned))
                        # Marquer qu'on a trouvé des données principales
                        if len(cleaned) > 50 and not cleaned.startswith("http"):
                            found_description = True
                        elif cleaned.startswith("http") and "airtable.com" not in cleaned:
                            found_website = True
                        elif cleaned.startswith("www."):
                            found_website = True
                        elif 3 < len(cleaned) < 60 and not any(ord(c) > 127 for c in cleaned[:3]):
                            if not cleaned.startswith("http") and ";" not in cleaned:
                                found_company_name = True
                        # Détecter createdTime (date ISO)
                        elif "T" in cleaned and cleaned.count("-") >= 2 and cleaned.count(":") >= 2:
                            try:
                                from datetime import datetime
                                datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
                                found_created_time = True
                            except:
                                pass
            
            i += 1
        
        # Filtrer les valeurs qui ont été extraites après un [0, "00"] (nouvelles entreprises)
        # Trouver toutes les positions de [0, "00"] dans la plage d'extraction
        end_marker_positions = []
        for k in range(pos, min(next_pos, len(items))):
            item = items[k]
            if isinstance(item, list) and len(item) == 2 and item[0] == 0 and item[1] == "00":
                end_marker_positions.append(k)
        
        # Trouver le dernier [0, "00"] qui est suivi d'une nouvelle entreprise
        # et après lequel on a déjà extrait des données principales
        cutoff_position = next_pos  # Par défaut, garder toutes les valeurs
        
        for end_pos in reversed(end_marker_positions):  # Commencer par le dernier
            # Vérifier si on a déjà extrait des données avant ce [0, "00"]
            has_data_before = False
            for pos_val, value in values:
                if pos_val < end_pos:
                    has_data_before = True
                    break
            
            if has_data_before:
                # Vérifier s'il y a une nouvelle entreprise après ce [0, "00"]
                for j in range(end_pos + 1, min(end_pos + 10, len(items))):
                    next_item = items[j]
                    # Ignorer les codes et métadonnées
                    if isinstance(next_item, int) and next_item < 200:
                        continue
                    if isinstance(next_item, list):
                        continue
                    if isinstance(next_item, str):
                        if (next_item.startswith("www.") or 
                            (next_item.startswith("http") and "airtable.com" not in next_item and "airtableusercontent.com" not in next_item) or
                            (len(next_item) > 50 and not next_item.startswith("http")) or
                            (3 < len(next_item) < 60 and not any(ord(c) > 127 for c in next_item[:3]) and ";" not in next_item)):
                            # Nouvelle entreprise détectée après ce [0, "00"]
                            cutoff_position = end_pos
                            break
                if cutoff_position < next_pos:
                    break
        
        # Filtrer les valeurs qui viennent après le cutoff
        filtered_values = [(pos_val, value) for pos_val, value in values if pos_val <= cutoff_position]
        
        # Utiliser les valeurs filtrées
        values = filtered_values
        
        # Maintenant, mapper les valeurs intelligemment
        # On va chercher les patterns dans l'ordre observé
        
        # 1. Industries - Market (premier texte avec emoji, généralement au début)
        for pos_val, value in values:
            if isinstance(value, str) and len(value) > 5:
                # Vérifier si c'est une Industries avec emoji
                if any(ord(c) > 127 for c in value[:5]) and ";" in value:
                    row_data["Macro-Industries - Market"] = value
                    break
        
        # 2. Website (URL qui n'est pas Airtable)
        # Vérifier que le Website correspond à l'entreprise (pas une autre entreprise)
        for pos_val, value in values:
            if isinstance(value, str) and value.startswith("http") and "airtable.com" not in value:
                # Ignorer les URLs Airtable même si "airtable.com" n'est pas dans le domaine
                if "airtableusercontent.com" in value or "v5.airtable" in value:
                    continue
                # Vérifier que cette URL ne vient pas après un [0, "00"] (nouvelle entreprise)
                comes_after_end_marker = False
                for k in range(pos_val - 1, max(pos_val - 15, pos), -1):
                    if k < len(items) and k >= pos:
                        prev_item = items[k]
                        if isinstance(prev_item, list) and len(prev_item) == 2 and prev_item[0] == 0 and prev_item[1] == "00":
                            # Vérifier s'il y a une nouvelle entreprise après ce [0, "00"]
                            for j in range(k + 1, min(k + 6, len(items))):
                                next_item = items[j]
                                if isinstance(next_item, str):
                                    if (next_item.startswith("www.") or 
                                        (next_item.startswith("http") and "airtable.com" not in next_item) or
                                        (len(next_item) > 50 and not next_item.startswith("http"))):
                                        comes_after_end_marker = True
                                        break
                            if comes_after_end_marker:
                                break
                if comes_after_end_marker and (found_company_name or found_description):
                    # Cette URL vient après un [0, "00"] suivi d'une nouvelle entreprise, ne pas l'utiliser
                    continue
                row_data["Website"] = value
                break
            # Aussi accepter les URLs qui commencent par www.
            elif isinstance(value, str) and value.startswith("www.") and "airtable.com" not in value:
                # Vérifier que cette URL ne vient pas après un [0, "00"]
                comes_after_end_marker = False
                for k in range(pos_val - 1, max(pos_val - 15, pos), -1):
                    if k < len(items) and k >= pos:
                        prev_item = items[k]
                        if isinstance(prev_item, list) and len(prev_item) == 2 and prev_item[0] == 0 and prev_item[1] == "00":
                            # Vérifier s'il y a une nouvelle entreprise après ce [0, "00"]
                            for j in range(k + 1, min(k + 6, len(items))):
                                next_item = items[j]
                                if isinstance(next_item, str):
                                    if (next_item.startswith("www.") or 
                                        (next_item.startswith("http") and "airtable.com" not in next_item) or
                                        (len(next_item) > 50 and not next_item.startswith("http"))):
                                        comes_after_end_marker = True
                                        break
                            if comes_after_end_marker:
                                break
                if comes_after_end_marker and (found_company_name or found_description):
                    # Cette URL vient après un [0, "00"] suivi d'une nouvelle entreprise, ne pas l'utiliser
                    continue
                row_data["Website"] = f"https://{value}"
                break
        
        # 3. Company logo (URL Airtable directUploadAttachment)
        for pos_val, value in values:
            if isinstance(value, str) and "airtable.com" in value and "directUploadAttachment" in value:
                row_data["Company logo"] = value
                break
        
        # 4. Current Program (texte contenant "Incubateur", "CDL", "Program", "Station", etc.)
        for pos_val, value in values:
            if isinstance(value, str) and any(keyword in value for keyword in [
                "Incubateur", "CDL", "Program", "Station", "Online", "TotalEnergies", "Akwa"
            ]) and "[" not in value:  # Pas un Batch
                row_data["Current Program"] = value
                break
        
        # 5. Batch (texte avec [] ou contenant "Batch")
        for pos_val, value in values:
            if isinstance(value, str) and ("[" in value and "]" in value or "Batch" in value):
                row_data["Batch"] = value
                break
        
        # 6. Industries - Product (deuxième texte avec emoji, généralement après Batch)
        industries_found = 0
        for pos_val, value in values:
            if isinstance(value, str) and len(value) > 5:
                if any(ord(c) > 127 for c in value[:5]) and ";" in value:
                    industries_found += 1
                    if industries_found == 2:  # La deuxième Industries
                        row_data["Macro-Industries - Product"] = value
                        break
        
        # 7. Description EN (texte long, généralement après Industries)
        for pos_val, value in values:
            if isinstance(value, str) and len(value) > 80:
                # Vérifier que ce n'est pas une URL ou autre
                if not value.startswith("http") and "Description EN" not in row_data:
                    # Vérifier que ça ressemble à une description (contient des mots communs)
                    if any(word in value.lower() for word in ["the", "is", "are", "and", "for", "with", "that", "this"]):
                        row_data["Description EN"] = value
                        break
        
        # 8. Company Name (texte court, généralement après la description, pas d'emoji, pas une description)
        # Chercher après la description si elle existe
        search_start = 0
        for pos_val, value in values:
            if value == row_data.get("Description EN"):
                # Trouver la position de la description et chercher après
                for idx, (p, v) in enumerate(values):
                    if v == value:
                        search_start = idx + 1
                        break
                break
        
        for pos_val, value in values[search_start:]:
            if isinstance(value, str) and 3 < len(value) < 60:
                # Ignorer les dates
                if "T" in value and value.count("-") >= 2 and value.count(":") >= 2:
                    continue
                
                # Ignorer les URLs
                if value.startswith("http") or value.startswith("www."):
                    continue
                
                # Ignorer les noms de fichiers (extensions communes)
                if any(value.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".svg", ".gif", ".pdf", ".webp", ".jpeg"]):
                    continue
                
                # Ignorer les noms contenant "logo", "Logo", "image", etc.
                if any(word in value.lower() for word in ["logo", "image", "copy", "jpg", "png", "svg"]):
                    continue
                
                # Pas d'emoji au début
                if any(ord(c) > 127 for c in value[:3]):
                    continue
                
                # Pas une description (pas de mots comme "the", "is", etc. au début)
                first_words = value.split()[:3]
                if any(word.lower() in ["the", "is", "are", "and", "for", "with", "that", "this", "we", "our"] 
                      for word in first_words):
                    continue
                
                # Pas déjà mappé
                if value not in row_data.values():
                    row_data["Company Name"] = value
                    break
        
        # 9. createdTime (date ISO)
        for pos_val, value in values:
            if isinstance(value, str) and "T" in value and value.count("-") >= 2 and value.count(":") >= 2:
                try:
                    # Vérifier que c'est une date valide
                    from datetime import datetime
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
                    row_data["createdTime"] = value
                    found_created_time = True
                    break
                except:
                    pass
        
        # Nettoyage final : vérifier la cohérence entre Company Name et Website
        # Si le Website ne correspond pas au Company Name, le supprimer
        company_name = row_data.get("Company Name", "").lower()
        website = row_data.get("Website", "").lower()
        
        if website:
            # Trouver la position du website dans les items
            website_pos = None
            for pos_val, value in values:
                value_str = str(value).lower()
                if value_str == website or value_str == website.replace("https://", "").replace("http://", "").replace("www.", ""):
                    website_pos = pos_val
                    break
            
            # Si on a trouvé la position, vérifier si elle vient après un [0, "00"]
            if website_pos:
                comes_after_end_marker = False
                for k in range(website_pos - 1, max(website_pos - 15, pos), -1):
                    if k < len(items) and k >= pos:
                        prev_item = items[k]
                        if isinstance(prev_item, list) and len(prev_item) == 2 and prev_item[0] == 0 and prev_item[1] == "00":
                            comes_after_end_marker = True
                            break
                
                if comes_after_end_marker and (found_company_name or found_description):
                    # Ce website vient après un [0, "00"], c'est une autre entreprise
                    if "Website" in row_data:
                        del row_data["Website"]
                
                # Vérifier aussi la cohérence avec le Company Name
                elif company_name:
                    website_domain = website.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
                    company_keywords = [w for w in company_name.split() if len(w) > 3]
                    # Si le domaine ne contient aucun mot-clé du company name, c'est suspect
                    if company_keywords and not any(kw in website_domain for kw in company_keywords):
                        # Vérifier si c'est vraiment le website de cette entreprise
                        if comes_after_end_marker or (website_pos and website_pos > pos + 20):
                            # Ce website est trop loin ou vient après un marqueur, c'est suspect
                            if "Website" in row_data:
                                del row_data["Website"]
        
        # Ajouter toutes les valeurs brutes pour référence (limitées)
        # Utiliser les valeurs filtrées (déjà filtrées plus haut)
        all_raw = [v for _, v in values[:30]]  # Limiter à 30 valeurs
        if all_raw:
            row_data["_all_values"] = all_raw
        
        rows.append(row_data)
    
    return rows


def deduplicate_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Déduplique les lignes en se basant sur Company Name + Website plutôt que sur l'ID.
    Les mêmes IDs peuvent représenter des entreprises différentes dans le flux sérialisé.
    """
    seen = set()
    unique_rows = []
    
    for row in rows:
        # Créer une clé unique basée sur Company Name et Website
        company_name = row.get("Company Name", "").strip()
        website = row.get("Website", "").strip()
        
        # Si on a un Company Name, l'utiliser comme clé principale
        if company_name:
            key = f"name:{company_name}"
        # Sinon, utiliser Website
        elif website:
            key = f"website:{website}"
        # Sinon, utiliser Description comme fallback
        elif row.get("Description EN"):
            desc = str(row.get("Description EN", ""))[:50].strip()
            key = f"desc:{desc}"
        # Dernier recours : utiliser l'ID + un hash des valeurs
        else:
            values_str = str(sorted(row.items()))[:100]
            key = f"id:{row.get('id', 'unknown')}:{hash(values_str)}"
        
        # Si cette clé n'a pas été vue, ajouter la ligne
        if key not in seen:
            seen.add(key)
            # Créer un ID unique pour cette ligne (basé sur l'index)
            row["_unique_id"] = f"row_{len(unique_rows)}"
            unique_rows.append(row)
        else:
            # Si on a déjà vu cette clé, on peut fusionner seulement si les données sont complémentaires
            # Pour l'instant, on ignore les doublons
            pass
    
    return unique_rows


def link_related_data(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Lie les données associées (comme Batch qui correspond à Current Program).
    Regroupe les lignes qui partagent des références communes.
    """
    # Créer un index des lignes par Current Program
    program_to_rows = {}
    batch_rows = []  # Lignes qui ont seulement un Batch
    
    # Première passe : indexer par Current Program et identifier les lignes Batch
    for row in rows:
        program = row.get("Current Program")
        batch = row.get("Batch")
        
        # Si la ligne a un Current Program, l'indexer
        if program:
            if program not in program_to_rows:
                program_to_rows[program] = []
            program_to_rows[program].append(row)
        
        # Si la ligne a seulement un Batch (pas d'autres données importantes), la marquer
        if batch and not program and not row.get("Website") and not row.get("Company Name") and not row.get("Description EN"):
            batch_rows.append(row)
    
    # Deuxième passe : lier les Batch aux lignes avec Current Program correspondant
    merged_rows = {}
    batch_ids_to_remove = set()
    
    # D'abord, copier toutes les lignes principales
    for row in rows:
        row_id = row.get("id")
        if row_id:
            merged_rows[row_id] = row.copy()
    
    # Ensuite, lier les Batch
    for batch_row in batch_rows:
        batch = batch_row.get("Batch")
        if not batch:
            continue
        
        # Extraire le nom du programme depuis le Batch (format: "[Program] ...")
        program_name = None
        if "[" in batch and "]" in batch:
            program_name = batch.split("]")[0].replace("[", "").strip()
        
        if program_name:
            # Chercher une ligne avec ce Current Program
            found_match = False
            for linked_row in program_to_rows.get(program_name, []):
                linked_id = linked_row.get("id")
                if linked_id and linked_id in merged_rows:
                    # Fusionner le Batch dans la ligne correspondante
                    if "Batch" not in merged_rows[linked_id] or not merged_rows[linked_id]["Batch"]:
                        merged_rows[linked_id]["Batch"] = batch
                    found_match = True
                    break
            
            # Si on a trouvé une correspondance, marquer cette ligne Batch pour suppression
            if found_match:
                batch_ids_to_remove.add(batch_row.get("id"))
    
    # Retourner les lignes fusionnées (sans les Batch isolés qui ont été liés)
    result = []
    for row_id, row in merged_rows.items():
        if row_id not in batch_ids_to_remove:
            result.append(row)
    
    return result


def organize_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Organise les données scrapées avec les valeurs réelles."""
    payload = data.get("payload", {})
    
    # Si le payload contient "items", utiliser directement
    if "items" in payload:
        items = payload["items"]
    elif isinstance(payload, dict) and "error" not in payload:
        # Essayer de trouver items ailleurs
        items = payload.get("data", {}).get("items", [])
        if not items:
            items = []
    else:
        items = []
    
    if not items:
        return {
            "error": "No items found in payload",
            "payload_keys": list(payload.keys()) if isinstance(payload, dict) else [],
        }
    
    # Extraire colonnes d'abord
    columns = extract_columns_direct(items)
    
    # Extraire les lignes avec leurs valeurs réelles
    rows = extract_rows_with_values(items, columns)
    
    # Dédupliquer les lignes basé sur Company Name/Website plutôt que sur ID
    # (les mêmes IDs peuvent représenter des entreprises différentes)
    rows = deduplicate_rows(rows)
    
    # Lier les données associées (Batch, etc.)
    rows = link_related_data(rows)
    
    # Créer le mapping colonne ID -> nom
    column_mapping = {col["id"]: col.get("name") or col["id"] for col in columns}
    
    return {
        "metadata": {
            "source_url": data.get("url", ""),
            "status_code": data.get("status_code", 0),
            "content_type": data.get("content_type", ""),
            "total_items": len(items),
        },
        "columns": columns,
        "rows": rows,  # Maintenant avec les valeurs réelles
        "column_mapping": column_mapping,
        "statistics": {
            "total_columns": len(columns),
            "total_rows": len(rows),
        },
    }


# ============================================================================
# PARTIE 3: FONCTION PRINCIPALE
# ============================================================================

def extract_params_from_url(url: str) -> Optional[Dict[str, str]]:
    """Extrait les paramètres depuis l'URL Airtable."""
    try:
        # Format: https://airtable.com/appXXX/shrXXX/tblXXX?viewControls=on
        # ou: https://airtable.com/shrXXX
        parts = url.replace("https://airtable.com/", "").split("/")
        
        params = {}
        if len(parts) >= 1:
            if parts[0].startswith("app"):
                params["application_id"] = parts[0]
            if len(parts) >= 2 and parts[1].startswith("shr"):
                params["share_id"] = parts[1]
            if len(parts) >= 3 and parts[2].startswith("tbl"):
                params["table_id"] = parts[2]
        
        # Extraire view_id depuis les query params si présent
        if "?" in url:
            query_part = url.split("?")[1]
            if "view=" in query_part:
                view_part = query_part.split("view=")[1].split("&")[0]
                if view_part.startswith("viw"):
                    params["view_id"] = view_part
        
        return params if params else None
    except Exception:
        return None


def main():
    """Fonction principale complète."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Scrape, organize and extract Airtable data")
    parser.add_argument("url", nargs="?", help="Airtable shared view URL")
    parser.add_argument("--output", "-o", default="airtable_extracted.json", help="Output file path")
    parser.add_argument("--cookie", help="Cookie header for authentication (or use AIRTABLE_COOKIE env var)")
    
    args = parser.parse_args()
    
    # URL par défaut ou depuis les arguments
    table_url = args.url or "https://airtable.com/appfLUDj8A9RFqyxy/shrGtTkoHk6QOpsrT/tbluZLSM3l4mENfIk?viewControls=on"
    
    # Cookie depuis argument ou variable d'environnement
    cookie = args.cookie or os.getenv("AIRTABLE_COOKIE")
    
    print("=" * 70)
    print("🔍 Airtable Complete Scraper & Organizer")
    print("=" * 70)
    print(f"URL: {table_url}")
    print()
    
    # Étape 1: Scraping
    print("📥 ÉTAPE 1: Scraping des données depuis Airtable...")
    try:
        config = AirtableRequestConfig()
        
        # Essayer d'extraire les paramètres depuis l'URL
        url_params = extract_params_from_url(table_url)
        if url_params:
            if "application_id" in url_params:
                config.application_id = url_params["application_id"]
            if "share_id" in url_params:
                config.share_id = url_params["share_id"]
            if "view_id" in url_params:
                config.view_id = url_params["view_id"]
        
        raw_data = fetch_airtable_data(config, cookie)
        
        if raw_data.get("status_code") != 200:
            print(f"❌ Erreur: Status {raw_data.get('status_code')}")
            return
        
        print(f"✅ Données récupérées (Status: {raw_data.get('status_code')})")
        print(f"   Content-Type: {raw_data.get('content_type', 'N/A')}")
        
    except Exception as e:
        print(f"❌ Erreur lors du scraping: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Étape 2: Organisation
    print("\n📊 ÉTAPE 2: Organisation et extraction des données...")
    try:
        organized = organize_data(raw_data)
        
        if "error" in organized:
            print(f"❌ Erreur: {organized['error']}")
            return
        
        stats = organized.get("statistics", {})
        rows = organized.get("rows", [])
        columns = organized.get("columns", [])
        
        print(f"✅ Données organisées:")
        print(f"   - Colonnes: {stats.get('total_columns', 0)}")
        print(f"   - Lignes: {stats.get('total_rows', 0)}")
        
        # Statistiques détaillées
        if rows:
            rows_with_website = sum(1 for r in rows if r.get("Website"))
            rows_with_name = sum(1 for r in rows if r.get("Company Name"))
            rows_with_desc = sum(1 for r in rows if r.get("Description EN"))
            rows_with_program = sum(1 for r in rows if r.get("Current Program"))
            rows_with_batch = sum(1 for r in rows if r.get("Batch"))
            rows_complete = sum(1 for r in rows if r.get("Website") and r.get("Company Name") and (r.get("Description EN") or r.get("Current Program")))
            
            print(f"\n📊 Statistiques d'extraction:")
            print(f"   - Lignes avec Website: {rows_with_website}")
            print(f"   - Lignes avec Company Name: {rows_with_name}")
            print(f"   - Lignes avec Description: {rows_with_desc}")
            print(f"   - Lignes avec Current Program: {rows_with_program}")
            print(f"   - Lignes avec Batch: {rows_with_batch}")
            print(f"   - Lignes complètes: {rows_complete}")
        
        # Afficher les colonnes
        if columns:
            print(f"\n📋 Colonnes trouvées ({len(columns)}):")
            for col in columns[:15]:
                name = col.get("name") or "N/A"
                col_type = col.get("type") or "N/A"
                col_id = col.get("id") or "N/A"
                print(f"   - {str(name):40s} ({col_id}) - {col_type}")
            if len(columns) > 15:
                print(f"   ... et {len(columns) - 15} autres colonnes")
        
    except Exception as e:
        print(f"❌ Erreur lors de l'organisation: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Étape 3: Sauvegarde
    print(f"\n💾 ÉTAPE 3: Sauvegarde dans {args.output}...")
    try:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(organized, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Fichier sauvegardé: {output_path.absolute()}")
        print(f"   Taille: {output_path.stat().st_size / 1024:.1f} KB")
        
    except Exception as e:
        print(f"❌ Erreur lors de la sauvegarde: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("\n" + "=" * 70)
    print("✅ Processus terminé avec succès!")
    print("=" * 70)


if __name__ == "__main__":
    main()

