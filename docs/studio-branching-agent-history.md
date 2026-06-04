# Studio Branching And Agent History

## Contexte

Quand un utilisateur édite un message humain au milieu d'une conversation, le Studio ne doit pas modifier l'historique existant. L'édition doit créer une nouvelle branche de conversation à partir de ce message, tout en conservant l'historique commun avant le point de branchement.

Le même principe s'applique aux agents et sous-agents persistés. Si un agent ou un sous-agent a été appelé avant le branchement, son historique ne doit pas être perdu. Si un agent ou un sous-agent a été appelé après le message édité, cet historique appartient uniquement à l'ancienne branche.

Le modèle attendu est proche de Git : des ancêtres communs partagés, puis des branches qui divergent.

## Objectif

Garantir qu'une édition de message humain relance la conversation depuis ce message sans fuite de mémoire entre branches.

Cela implique :

- préserver tous les messages et checkpoints existants ;
- créer une nouvelle version du message humain édité ;
- relancer les agents dans la nouvelle branche ;
- faire hériter les sous-agents du contexte de branche de leur parent ;
- empêcher un agent ou sous-agent de reprendre un historique appartenant à une autre version de la conversation.

## Principe Central

Un agent ne doit jamais tourner dans un thread global par agent.

Mauvais :

```txt
thread_id = conversation:mention:agent-a
```

Bon :

```txt
thread_id = conversation:branch:{branch_id}:mention:agent-a
```

Un sous-agent appelé par tool hérite du thread branché du parent :

```txt
conversation:branch:{branch_id}:mention:agent-a:ask_agent_b:agent-b
```

Si ce sous-agent appelle lui-même un autre agent :

```txt
conversation:branch:{branch_id}:mention:agent-a:ask_agent_b:agent-b:ask_agent_c:agent-c
```

Toute profondeur d'appel reste ainsi attachée à la bonne branche.

## Copy-On-Write

Lorsqu'une branche est créée, il ne faut pas copier immédiatement tous les historiques d'agents. Il faut créer une branche logique et ne matérialiser les nouveaux threads qu'à la première écriture.

Avant le fork :

```txt
H1 -> A1 -> H2(v1) -> A2
```

Après édition de `H2` :

```txt
branche originale:
H1 -> A1 -> H2(v1) -> A2

nouvelle branche:
H1 -> A1 -> H2(v2) -> A2'
```

`H1` et `A1` restent des ancêtres communs. `H2(v1)` et `A2` restent dans la branche originale. `H2(v2)` et `A2'` appartiennent à la nouvelle branche.

Les messages qui suivent le message édité restent sur l'ancienne branche. Ils ne sont pas rejoués automatiquement sur la nouvelle branche.

Exemple :

```txt
main:
H1 -> A1 -> H2(v1) -> A2 -> H3 -> A3

edit H2:
H1 -> A1 -> H2(v2) -> A2'
```

`H3` reste dans la branche originale. Un éventuel cherry-pick ou replay manuel de `H3` serait une fonctionnalité séparée.

## Frontière De Checkpoints

Pour que les agents conservent l'historique antérieur au fork sans récupérer l'historique postérieur, chaque événement public important doit pouvoir indiquer une frontière de checkpoints.

Chaque événement public branchable doit référencer deux frontières :

- `frontier_before_event_id` : l'état cohérent immédiatement avant l'événement ;
- `frontier_after_event_id` : l'état cohérent immédiatement après l'événement, si l'événement a produit un run ou une mutation stable.

Quand l'utilisateur édite un message humain, la nouvelle branche doit partir de `frontier_before_event_id`. C'est ce qui conserve l'historique commun avant le message, sans reprendre les réponses et sous-historiques créés après l'ancienne version du message.

Exemple :

```txt
public_event A1
frontier:
  mention:agent-a                      -> checkpoint 42
  mention:agent-a/ask:agent-b           -> checkpoint 17
  mention:agent-a/ask:agent-b/ask:c     -> checkpoint 8
```

Quand une nouvelle branche démarre après `A1`, cette frontière dit :

- `agent-a` peut repartir du checkpoint 42 ;
- si `agent-a` rappelle `agent-b`, `agent-b` peut repartir du checkpoint 17 ;
- si `agent-b` rappelle `agent-c`, `agent-c` peut repartir du checkpoint 8.

Si un sous-agent n'existait pas avant le fork, il démarre sans historique dans la nouvelle branche.

La frontière doit être capturée après chaque run terminal, pas seulement après les runs réussis. Les statuts terminaux incluent au minimum :

- `success` ;
- `stopped` ;
- `failed` ;
- `empty` ;
- `interrupted` ;
- `cascade-limited`.

Chaque snapshot de frontière doit indiquer si le checkpoint est utilisable pour créer une branche ou pour continuer un thread.

```txt
frontier_snapshot
- run_id
- branch_id
- logical_thread_key
- checkpoint_id
- status
- usable_for_fork
- usable_for_continue
```

Un checkpoint est considéré stable uniquement si aucune écriture mutable, aucun tool call, aucun child run et aucun effet causal conversationnel n'est encore en cours.

Règles recommandées :

- `usable_for_fork = true` uniquement après une frontière propre : run terminal, tool calls terminés ou annulés proprement, enfants terminés ou explicitement détachés, état Studio persisté ;
- `usable_for_continue = true` pour un succès, une pause contrôlée, une interruption coopérative ou un arrêt qui produit un checkpoint cohérent ;
- `usable_for_continue = false` pour un kill brutal, un crash, un timeout non checkpointé ou une interruption pendant une écriture/tool call.

Pour un agent arrêté de force :

- si l'arrêt produit un checkpoint cohérent, ce checkpoint peut être `usable_for_continue = true` ;
- si l'arrêt coupe un tool ou une écriture en cours, ce checkpoint doit être `usable_for_continue = false` ;
- dans ce cas, une continuation ou une nouvelle injection de prompt doit repartir du dernier checkpoint stable précédent.

Le système ne doit donc pas choisir aveuglément le dernier checkpoint connu. Il doit choisir le dernier checkpoint utilisable pour l'opération demandée.

## Fork Technique De Checkpoints

Le fork technique doit être encapsulé dans un service dédié, par exemple `ThreadForker`.

Responsabilité :

```txt
fork_checkpoint(
  source_physical_thread_id,
  source_checkpoint_id,
  target_physical_thread_id
)
```

La stratégie recommandée est de cloner physiquement le checkpoint source vers un nouveau `thread_id`.

Le replay ne doit pas être utilisé comme fallback de production au démarrage. Il peut réexécuter des tools, recréer des effets externes ou diverger du run original. Si le clone de checkpoint n'est pas fiable, la fonctionnalité de branchement doit être bloquée pour ce cas plutôt que de créer une branche approximative.

Un spike LangGraph doit valider explicitement :

- qu'un checkpoint peut être copié vers un nouveau `thread_id` ;
- que la nouvelle branche peut continuer sans lire les checkpoints postérieurs de la branche source ;
- que les subgraphs et checkpointers imbriqués conservent bien leur scope ;
- que le clone ne réexécute aucun tool.

## Résolution D'un Thread D'agent

Un tool `ask_*` ne doit jamais choisir l'historique par nom d'agent seul.

Mauvais :

```txt
ask_architect -> thread architect global
```

Bon :

```txt
ask_architect -> resolve(
  branch_id,
  parent_logical_thread_key,
  relation_id,
  target_agent_id
)
```

Le contexte transmis à un tool d'agent doit contenir au minimum :

```txt
branch_id
parent_logical_thread_key
parent_physical_thread_id
relation_id
fork_frontier
```

Le tool résout ensuite le thread cible :

1. Chercher si un `branch_thread` existe déjà pour `(branch_id, logical_thread_key)`.
2. S'il existe, continuer dans ce thread physique.
3. Sinon, chercher un checkpoint dans la frontière héritée.
4. S'il existe, créer un nouveau thread physique branché depuis ce checkpoint.
5. Sinon, créer un nouveau thread vide dans cette branche.

## Agents Persistés Et Appels Successifs

Un agent appelé via un tool `ask_*` peut être persisté. Dans ce cas, deux appels successifs depuis le même parent et la même relation logique doivent continuer le même historique d'agent.

La clé logique d'un sous-thread ne doit pas être l'identifiant d'appel individuel. Elle doit représenter la relation persistée avec un identifiant stable :

```txt
logical_thread_key =
  workspace_id
  + root_conversation_id
  + parent_logical_thread_key
  + relation_id
  + target_agent_id
```

`relation_id` doit être un identifiant de configuration stable. Il ne doit pas être dérivé du nom affiché du tool, du label UI ou du nom courant de l'agent, car ces valeurs peuvent changer.

Le `branch_id` ne fait pas partie de l'identité logique. Il sert à résoudre le thread physique :

```txt
(branch_id, logical_thread_key) -> physical_thread_id
```

Deux appels successifs dans la même branche :

```txt
agent-a / ask_b / agent-b
```

doivent écrire dans le même historique persistant de `agent-b`.

Ils ne doivent pas créer automatiquement :

```txt
agent-a / ask_b / agent-b / call_1
agent-a / ask_b / agent-b / call_2
```

Si deux appels au même agent persisté arrivent en parallèle sur la même branche et la même clé logique, ils doivent être sérialisés. Deux runs concurrents ne doivent pas écrire dans le même thread physique.

Deux parents différents ne partagent pas le même historique persistant, même si l'agent cible est identique. Deux relations différentes ne partagent pas non plus le même historique, même si elles pointent vers le même agent.

Les appels individuels peuvent toujours être enregistrés comme événements ou tool calls, mais ils ne doivent pas définir l'identité de l'historique persistant.

## Données À Persister

### Messages Publics

Chaque événement public doit porter les informations de branche et de version.

```txt
conversation_events
- id
- logical_message_id
- version_parent_event_id
- branch_id
- parent_event_id
- frontier_before_event_id
- frontier_after_event_id
- author_id
- author_kind
- content
- created_at
```

`seq` peut rester comme ordre d'audit global, mais ne doit pas être le seul mécanisme pour reconstruire une branche visible.

### Événements De Contrôle

Un prompt injecté après un arrêt, une reprise manuelle, une annulation ou une commande interne ne doit pas être modélisé comme un message public si l'utilisateur ne l'a pas envoyé dans la conversation principale.

Ces événements doivent être branch-scoped et visibles dans l'activité technique de l'agent.

```txt
control_events
- id
- conversation_id
- branch_id
- logical_thread_key
- physical_thread_id
- parent_run_id
- kind
- content
- created_at
```

Un `control_event` peut influencer la continuation d'un agent, mais il ne devient visible dans la conversation principale que si un agent produit ensuite un événement public.

### Branches

```txt
conversation_branches
- id
- parent_branch_id
- origin_event_id
- origin_logical_message_id
- origin_previous_event_id
- created_at
- current
- archived_at
```

### Threads Branchés

```txt
branch_threads
- branch_id
- logical_thread_key
- physical_thread_id
- forked_from_branch_id
- forked_from_thread_id
- forked_from_checkpoint_id
- created_by_commit_id
- status
```

### Frontières De Checkpoints

```txt
thread_frontiers
- frontier_id
- conversation_id
- branch_id
- event_id
- event_boundary
- logical_thread_key
- physical_thread_id
- checkpoint_id
- parent_logical_thread_key
- usable_for_fork
- usable_for_continue
```

`event_boundary` vaut `before` ou `after`. Une édition de message humain utilise la frontière `before` de l'événement édité.

### États Runtime

Ces états doivent être scopés par branche :

```txt
agent_delivery_state
- conversation_id
- branch_id
- agent_id
- last_delivered_event_id
- queued
- running
- current_run_id
- current_snapshot_event_id
```

Même règle pour :

- queue items ;
- runs ;
- deliveries ;
- interrupts ;
- tool calls persistés ;
- generated UI associée à un run ;
- checkpoints exposés au Studio.

Chaque item de queue doit porter son `branch_id` dès sa création. Quand une nouvelle branche est créée, les items en attente de l'ancienne branche ne sont pas transférés. Ils restent attachés à leur branche d'origine et doivent être mis en pause par défaut si l'utilisateur quitte cette branche.

### États UI Branchés

L'état UI qui peut modifier ou reprendre une conversation doit aussi être scopé par branche.

```txt
studio_branch_ui_state
- conversation_id
- branch_id
- participant_id
- draft_content
- outbox_state
- editing_event_id
- selected_agent_id
- scroll_anchor_event_id
- updated_at
```

La clé minimale recommandée est :

```txt
conversation_id + branch_id + participant_id
```

Changer de version de message doit donc changer la branche active, pas seulement remplacer du texte à l'écran.

### Runs Et Frontières

Les runs doivent persister le contexte de branche et la frontière produite.

```txt
runs
- id
- conversation_id
- branch_id
- logical_thread_key
- physical_thread_id
- status
- stop_kind
- started_at
- completed_at
- stable_checkpoint_id
- latest_checkpoint_id
- checkpoint_stability
- usable_for_fork
- usable_for_continue
- commit_state
```

`stable_checkpoint_id` représente le dernier checkpoint cohérent connu pour continuer ou forker. `latest_checkpoint_id` peut pointer vers un checkpoint plus récent mais non utilisable si le run a été interrompu au mauvais moment.

`commit_state` vaut au minimum `pending` ou `committed`. Un run `pending` ne doit pas être visible comme frontière utilisable.

### Tool Call Edges

Les appels `ask_*` doivent persister l'arête causale entre le thread parent et le thread enfant.

```txt
tool_call_edges
- id
- commit_id
- branch_id
- parent_logical_thread_key
- parent_physical_thread_id
- relation_id
- target_agent_id
- child_logical_thread_key
- child_physical_thread_id
- run_id
- status
```

Cette table permet de reconstruire les sous-arbres d'agents et de vérifier qu'un sous-agent appartient bien à la branche et au parent attendus.

### Effets Externes

Les fichiers, appels API, commandes shell, actions réseau et autres side effects ne sont pas rewindables par le branching conversationnel.

```txt
external_side_effects
- id
- branch_id
- run_id
- agent_id
- tool_call_id
- kind
- target
- audit_payload
- not_rewindable
- created_at
```

Règles recommandées :

- artefact créé avant le fork : partagé et immutable ;
- artefact créé après le fork : branch-local ;
- effet externe : conservé comme audit, jamais annulé implicitement par un switch de branche.

### Atomicité Et Commit Causal

Chaque mutation causale importante doit être regroupée sous un `commit_id`.

Pour un appel agent vers agent persisté, l'unité logique doit inclure :

- le `run` parent ;
- le `tool_call_edge` ;
- le `branch_thread` enfant ;
- les checkpoints/frontières produits ;
- les statuts finaux.

Si le checkpointer et la base Studio ne peuvent pas être écrits dans une même transaction physique, le système doit utiliser un protocole `pending -> committed`.

Règles :

- aucune frontière `pending` ne peut être utilisée pour forker ou continuer ;
- aucun child thread `pending` ne doit apparaître comme historique disponible ;
- au démarrage, un repair/reconciliation job doit marquer les commits incomplets comme orphelins ou les finaliser si toutes les pièces existent ;
- un thread physique sans edge causal committed doit être conservé pour audit, mais jamais résolu comme historique normal.

## Invariants

1. Une édition ne modifie jamais un événement existant.
2. Une édition crée une nouvelle branche et une nouvelle version du message.
3. Une branche visible contient les ancêtres communs puis les événements propres à cette branche.
4. Un agent ne peut lire que les événements visibles de sa branche.
5. Un agent ne peut écrire que dans les threads physiques de sa branche.
6. Un sous-agent hérite toujours du `branch_id` et du thread logique de son parent.
7. Deux branches peuvent partager un checkpoint ancêtre, mais ne doivent jamais partager un thread mutable après le fork.
8. Un état d'agent ne doit jamais être global à toute la conversation s'il influence la reprise, la queue ou la mémoire.
9. Un run déjà démarré reste attaché à sa branche d'origine, même si l'utilisateur édite ensuite un message précédent.
10. Un tool `ask_*` vers un agent persisté doit résoudre un historique par relation logique, pas par invocation individuelle.
11. Les appels concurrents vers la même clé logique persistée doivent être sérialisés.
12. Les effets externes non conversationnels ne sont pas rewindables par le branching.
13. Une édition de message humain branche depuis la frontière `before` de ce message.
14. Un replay technique ne doit pas être utilisé comme fallback implicite au clone de checkpoint.
15. Un item de queue appartient définitivement à la branche qui l'a créé.
16. Une version de message active une branche, elle ne remplace pas seulement le contenu affiché.
17. Les identifiants `branch_id`, `logical_thread_key`, `physical_thread_id`, `run_id`, `commit_id` et `frontier_id` doivent être disponibles dans les traces et logs.

## Flow D'édition

Quand l'utilisateur édite un message humain :

1. Le backend vérifie que le message appartient à la branche visible courante.
2. Il récupère `frontier_before_event_id` sur l'événement édité.
3. Il crée une nouvelle branche depuis cette frontière `before`.
4. Il crée une nouvelle version du message humain édité dans cette branche.
5. Il initialise la frontière de checkpoints de la nouvelle branche depuis le point de fork.
6. Il initialise les états agents de la nouvelle branche au point de fork.
7. Il enfile les mentions du message édité dans la queue de la nouvelle branche.
8. Il switch le Studio sur la nouvelle branche.
9. Les agents répondent uniquement dans la nouvelle branche.

Les runs déjà en cours au moment de l'édition ne changent pas de branche. Ils continuent, réussissent, échouent ou sont arrêtés dans leur branche d'origine.

Les runs planifiés mais pas encore démarrés restent eux aussi attachés à leur branche d'origine. Si l'utilisateur quitte cette branche après l'édition, ces items doivent être mis en pause par défaut et ne reprendre que si l'utilisateur revient explicitement sur cette branche.

Si un nouveau prompt est injecté à un agent après un arrêt forcé, il doit être enregistré comme `control_event` branch-scoped et repartir de la dernière frontière `usable_for_continue = true` pour cette branche et ce thread logique.

Si aucune frontière `usable_for_continue = true` n'existe, l'injection doit être refusée ou transformée en nouveau run depuis la dernière frontière `usable_for_fork = true`.

## Exemple Complet

Conversation initiale :

```txt
main:
H1
A1
  private agent-a:
    ask_b -> checkpoint B12
    ask_c -> checkpoint C5
H2(v1)
A2
```

L'utilisateur édite `H2`.

Nouvelle branche :

```txt
branch_edit_h2:
H1
A1
H2(v2)
A2'
```

Quand `agent-a` répond à `H2(v2)` :

```txt
agent-a repart depuis son checkpoint après A1
```

Si `agent-a` rappelle `agent-b` :

```txt
agent-b repart depuis B12
```

Si `agent-a` appelle un agent jamais appelé avant :

```txt
nouveau thread vide dans branch_edit_h2
```

Ce que la nouvelle branche ne voit jamais :

```txt
H2(v1)
A2
threads et sous-threads créés après H2(v1)
```

## UI De Version Et Navigation

Un message humain qui possède plusieurs versions doit afficher un sélecteur de versions directement sur le message.

Changer de version revient à changer de branche.

Le Studio peut aussi proposer une vue globale en arbre pour visualiser la conversation principale et ses branches :

```txt
H1
└─ A1
   ├─ H2(v1)
   │  └─ A2
   │     └─ H3
   │        └─ A3
   └─ H2(v2)
      └─ A2'
```

Le sélecteur de version est l'entrée locale. La vue arbre est l'entrée structurelle.

La vue arbre principale doit afficher la conversation principale et ses versions. Elle ne doit pas afficher par défaut tout l'arbre interne des agents, sous-agents et tool calls, car cette vue deviendrait rapidement illisible.

Une vue technique/debug peut afficher l'arbre complet :

```txt
branch
└─ public conversation
   └─ agent-a
      └─ relation ask_b -> agent-b
         └─ relation ask_c -> agent-c
```

Quand l'utilisateur sélectionne une ancienne version, le Studio doit activer la branche associée. Les drafts, outbox et états d'édition doivent être restaurés depuis l'état UI branché.

L'agent ne doit pas recevoir d'information spéciale indiquant qu'il est sur une branche alternative. Il reçoit simplement l'historique cohérent de sa branche.

## Risques À Éviter

### Fuite Par Thread Id Global

Si le `thread_id` ne contient pas `branch_id`, un agent peut reprendre un checkpoint d'une autre branche.

### Fuite Par AgentDeliveryState Global

Si `last_delivered_seq` est global par agent, l'agent peut croire avoir déjà traité des événements d'une branche qu'il n'a jamais vue, ou inversement reprendre trop loin.

### Fuite Par Tool Call

Si un tool `ask_*` résout seulement par `target_agent_id`, les sous-agents persistés mélangent les branches.

### Fuite Par UI Seulement

Filtrer l'UI par `branch_id` ne suffit pas. Le runtime, les queues, les checkpoints et les tools doivent être branch-aware.

### Replay Implicite De Messages Suivants

Les messages humains postérieurs au point d'édition ne doivent pas être recopiés automatiquement sur la nouvelle branche. Cela créerait un faux historique où l'utilisateur semble avoir répondu à une réponse qui n'existe pas dans cette branche.

### Checkpoint Non Stable

Un run arrêté ou échoué peut produire un checkpoint plus récent mais non cohérent. Le système doit distinguer dernier checkpoint observé et dernier checkpoint utilisable.

### Concurrence Sur Agent Persisté

Deux appels parallèles au même agent persisté, dans la même branche et sur la même relation logique, peuvent corrompre l'ordre de l'historique si le système ne les sérialise pas.

### Effets De Bord Externes

Les effets comme modification de fichiers, commandes shell, appels API ou actions réseau ne peuvent pas être rewindés par le branching conversationnel. Ils doivent être traités comme des effets externes audités, pas comme de l'état conversationnel réversible.

### Relation Id Instable

Si la clé logique d'un agent persisté dépend d'un nom affiché ou d'un tool name renommable, un renommage peut casser la continuité de l'historique. La clé doit utiliser un `relation_id` stable.

### Queue Non Branchée

Si les queue items ne portent pas leur `branch_id`, un run en attente peut démarrer dans une branche que l'utilisateur ne regarde plus ou publier une réponse dans le mauvais historique.

### Replay Technique

Si le fork repose sur un replay implicite, des tools peuvent être réexécutés et produire des side effects dupliqués. Le fork doit cloner un checkpoint ou échouer explicitement.

### Observabilité Insuffisante

Sans `branch_id`, `logical_thread_key`, `physical_thread_id`, `run_id`, `commit_id`, `tool_call_edge_id` et `frontier_id` dans les logs et traces, les fuites entre branches seront difficiles à diagnostiquer.

## Ancien Historique

Les conversations créées avant l'introduction de ce modèle ne doivent pas être migrées partiellement.

Chaque conversation doit porter un `history_schema_version`. Si la version n'est pas branch-aware, deux options sûres existent :

1. les supprimer ;
2. les ignorer et forcer la création de nouvelles conversations branch-aware.

Une migration partielle est risquée car elle pourrait créer des conversations visibles mais sans `branch_id`, `logical_message_id`, `parent_event_id` ou frontières de checkpoints fiables.

La recommandation est de supprimer ou masquer explicitement l'ancien historique Studio non branch-aware au premier démarrage de cette fonctionnalité. Une conversation ancienne ne doit pas être ouverte en mode partiellement compatible.

## Rétention Et Threads Orphelins

La politique de rétention recommandée est de conserver le plus d'historique possible.

```txt
retention: forever
cleanup: explicit only
orphan policy: keep + mark orphaned
user deletion: archive only
admin/dev deletion: hard delete allowed only with explicit cascade
```

Un thread peut devenir non référencé dans ces cas :

- une branche est supprimée ou archivée ;
- un run crée un child thread puis échoue avant de publier son edge causal ;
- un tool call démarre, mais le parent est arrêté avant commit ;
- une transaction partielle laisse un thread physique sans frontier ;
- du debug ou des tests créent des threads temporaires ;
- une corruption ou une évolution du modèle rend un lien impossible à résoudre.

Le système ne doit pas supprimer automatiquement ces threads. Il doit les marquer comme orphelins et les conserver pour audit ou récupération manuelle.

L'utilisateur peut archiver ou masquer une branche, mais pas la supprimer physiquement dans le premier design. Le hard delete doit rester une opération admin/dev explicitement outillée.

## Stratégie D'implémentation Recommandée

1. Introduire `branch_id` dans les contrats runtime critiques.
2. Scoper `AgentDeliveryState`, queues, runs et deliveries par branche.
3. Générer des `thread_id` branchés pour les agents mentionnés.
4. Faire propager `branch_id`, `logical_thread_key`, `physical_thread_id`, `relation_id` et `fork_frontier` à tous les tools `ask_*`.
5. Persister les `branch_threads` en copy-on-write.
6. Persister les `thread_frontiers` avec frontières `before` et `after` au moment des réponses publiques et checkpoints importants.
7. Faire l'édition de message comme création de branche + nouvelle version d'événement.
8. Mettre à jour le Studio pour afficher et switcher les versions/branches.
9. Sérialiser les runs qui écrivent dans le même `(branch_id, logical_thread_key)`.
10. Ajouter un spike LangGraph pour valider le fork de checkpoint vers un nouveau `thread_id`.
11. Ajouter un protocole `pending -> committed` pour les mutations causales multi-tables.
12. Persister et restaurer l'état UI branché.
13. Auditer les side effects externes comme non rewindables.
14. Supprimer ou ignorer les anciennes conversations non branch-aware.
15. Ajouter les identifiants de branche, run, thread, frontier et commit dans les logs/traces.

## Plan De Tests Minimal

Le comportement doit être validé avec un test profond d'au moins cinq niveaux d'agents persistés.

Scénario :

```txt
main branch
H1 mentions A

A calls B
B calls C
C calls D
D calls E
E replies
D replies
C replies
B replies
A replies publicly

H2 mentions A
A calls B again
B continues same history in the same branch
```

Puis l'utilisateur édite `H2`.

Assertions minimales :

- la nouvelle branche garde la frontière après `A1` ;
- `A` repart du bon checkpoint pré-fork ;
- `B`, `C`, `D` et `E` repartent des checkpoints pré-fork ;
- aucun checkpoint créé après `H2(v1)` n'est visible ou réutilisé dans `H2(v2)` ;
- deux appels successifs à `B` dans une même branche continuent le même historique ;
- deux branches n'écrivent jamais dans le même `physical_thread_id` ;
- un run arrêté utilise le dernier checkpoint stable `usable_for_continue = true` ;
- un checkpoint non stable ne peut pas devenir la base implicite d'une nouvelle continuation.

Tests supplémentaires recommandés :

- éditer un message humain au milieu d'une conversation et vérifier que la nouvelle branche part de `frontier_before_event_id` ;
- injecter un prompt après arrêt forcé et vérifier qu'il devient un `control_event` branch-scoped ;
- vérifier qu'un kill brutal sans checkpoint stable refuse la continuation directe ;
- appeler le même agent persisté depuis deux parents différents et vérifier que les historiques ne se mélangent pas ;
- appeler le même agent persisté via deux relations différentes et vérifier que les historiques ne se mélangent pas ;
- lancer deux appels concurrents vers la même clé logique et vérifier leur sérialisation ;
- créer un queue item sur l'ancienne branche, switcher vers une nouvelle branche, puis vérifier que l'item ancien reste en pause ;
- produire un side effect après fork et vérifier qu'il reste audité mais non rewindé ;
- sélectionner une ancienne version de message et vérifier que drafts/outbox/édition sont branch-scoped ;
- ouvrir une conversation non branch-aware et vérifier qu'elle est supprimée, masquée ou rejetée proprement ;
- simuler un commit incomplet et vérifier que le repair marque le thread comme orphelin ou le finalise sans le rendre visible à tort.

## Résumé

La solution pérenne est :

```txt
frontière récursive de checkpoints
+ thread ids branchés
+ états runtime scopés par branche
+ copy-on-write à la première écriture
```

C'est ce qui permet de conserver tout l'historique avant un branchement, tout en garantissant que les agents et sous-agents persistés ne reprennent jamais la mémoire d'une autre version de la conversation.
