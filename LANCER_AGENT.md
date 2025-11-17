# Guide pour lancer votre premier agent

## ✅ Configuration déjà faite

Votre fichier `.env` est déjà configuré avec:
- `OPENAI_API_KEY` : ✅ Configuré
- `OPENAI_API_URL` : ✅ Configuré (https://litellm.internal.syntia.app)

## 🚀 Lancer l'agent

### Option 1: Avec l'environnement virtuel (recommandé)

```bash
# Activer l'environnement virtuel
source .venv/bin/activate

# Lancer l'exemple
python3 examples/my_first_agent.py
```

### Option 2: Avec uv (recommandé par le projet)

```bash
# Lancer directement avec uv
uv run examples/my_first_agent.py
```

### Option 3: Modifier la tâche

Vous pouvez modifier la tâche dans `examples/my_first_agent.py` :

```python
task = "Votre tâche personnalisée ici"
```

## 📝 Exemples de tâches

- `"Find the number 1 post on Show HN"`
- `"Search Google for 'browser automation' and tell me the top 3 results"`
- `"Go to github.com and find the number of stars for the browser-use repository"`

## 🔧 Dépannage

Si vous avez des erreurs:

1. **Vérifier que l'environnement virtuel est activé**
   ```bash
   source .venv/bin/activate
   ```

2. **Vérifier les dépendances**
   ```bash
   uv sync --dev --all-extras
   ```

3. **Vérifier que Chromium est installé**
   ```bash
   uvx browser-use install
   ```

4. **Vérifier les variables d'environnement**
   ```bash
   cat .env | grep OPENAI
   ```

