# Agent history web UI

Interface locale pour lire l'historique persistant des agents depuis le
checkpointer SQLite LangGraph.

## Lancer

Depuis la racine du repo:

```bash
uv run python webui/server.py --db .coding-agents/checkpoints.sqlite --port 8765
```

Puis ouvrir:

```text
http://127.0.0.1:8765
```

## Ce qui est affiché

- vue par agent ou en colonnes dynamiques depuis le manifest runtime;
- option de scroll synchronisé quand des timestamps existent;
- blocs de réflexion collapsed par défaut;
- appels outils collapsed par défaut;
- appels `ask_product_analyst` / `ask_software_architect` visibles sans input ni
  résultat dans la colonne manager;
- appels `task` vers les agents non persistants visibles depuis la colonne
  manager, avec ouverture d'un drawer de transcript complet;
- compteurs d'en-tête qui distinguent les consultations d'agents persistants
  des appels `task` vers les sous-agents non persistants;
- ajout temporaire d'un run non persistant comme colonne dans la vue
  multi-colonnes;
- rafraîchissement live par polling, avec auto-scroll seulement si la vue est
  déjà en bas.

## API locale

- `GET /api/state` expose les agents persistants et les résumés des runs
  `tools:*`;
- `GET /api/task-run?thread_id=...&run_id=tools:...` charge le transcript
  complet d'un run non persistant à la demande.
