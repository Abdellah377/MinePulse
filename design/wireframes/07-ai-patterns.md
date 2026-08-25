# WF-07 — Patterns IA intégrés (tous les écrans)

**Principe :** pas de page Chatbot. L'IA s'insère dans le workflow.

**V1 :** emplacements visibles, copy mockée, badge « Aperçu — non connecté ».

---

## Matrice d'intégration

| Écran | Emplacement | Contenu type |
|---|---|---|
| Exceptions | Bandeau bas Insights | Résumé poste + cause + action |
| Carte | Chips carte / Info rapide | Congestion, idle, trajet anormal |
| Film | Panneau détail segment | Pourquoi / confiance / preuves |
| Parc | Expand cycle | Pourquoi cycle long |
| Événements | Panneau détail | Explication, impact, action, priorité |
| Inspecteur | Onglet IA | Pourquoi + action sur l'engin |
| Performance (plus tard) | Résumé d'analyse | Prédiction fin de poste |

---

## Anatomie d'un slot IA (composant design)

```
┌─ IA · Pourquoi ─────────────── Aperçu ─┐
│ Titre court                            │
│ Corps 2–4 lignes                       │
│ Confiance: XX% (mock)                  │
│ Preuves: · … · …                       │
│ Action: …                              │
└────────────────────────────────────────┘
```

Règles visuelles (hi-fi) :
- Bordure légère, fond surface, accent vert OCP discret sur le label « IA »
- Jamais neon / glass  
- Toujours indiquer que c'est un aperçu tant que LangGraph n'est pas branché  

---

## Questions produit couvertes

1. **Quoi** — données live (Parc, Carte, Film, Événements)  
2. **Pourquoi** — slots Explain  
3. **Ensuite** — prediction mock sur Exceptions / Performance  
4. **Faire** — recommended action dans Événements + Exceptions  

---

## Hors scope V1

- LangGraph  
- Chat libre  
- Optimisation réelle de cycle  
- Appels FMS  
