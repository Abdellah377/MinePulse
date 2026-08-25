# WF-06 — Inspecteur équipement (lo-fi gris)

**Type :** tiroir droit (400 px) — pas une page nav  
**Ouverture depuis :** Exceptions, Carte, Film, Parc, Événements  

---

## Layout

```
┌─ INSPECTEUR ────────────────────┐
│ 305 · CAT 793 · [Attente]  [↗] │
│ Conducteur · Zone · Poste       │
│ Tâche: Attente de chargement…   │
├─────────────────────────────────┤
│ [Aperçu|Cycle|KPIs|Maint.|IA]   │
├─────────────────────────────────┤
│ Télémétrie 2×2                  │
│ Vitesse | Gasoil | Moteur | Santé│
│ Mini-film du poste              │
│ KPIs: NV, attente %, idle %     │
└─────────────────────────────────┘
```

### Onglets

| Onglet | Contenu |
|---|---|
| Aperçu | Statut, tâche, télémétrie, mini film |
| Cycle | Étapes cycle actuel (comme expand Parc) + vs moyenne |
| KPIs | TD, TU, heures, arrêts ventilés |
| Maint. | Prochain entretien, historique mock |
| IA | Pourquoi / Recommandation — placeholder |

`[↗]` = ouvrir page plein écran optionnelle `/equipement/:id` (même contenu).

---

## Slot IA (onglet)

```
Raison probable: …
Confiance: …%
Preuves: …
Action suggérée: …
[Non actif — réservé LangGraph]
```
