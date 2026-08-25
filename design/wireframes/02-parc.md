# WF-02 — Parc (lo-fi gris)

**Workspace :** Supervision › Parc  
**Ancêtre OPM :** Tableau de bord camions  
**Objectif :** trier / scanner la flotte sans tableur à 20 colonnes tronquées.

---

## Utilisateur principal

Chef de poste (tri attentes / idle) ; régulateur (affectation).

---

## Principe de redesign

| OPM | MinePulse |
|---|---|
| Toutes les colonnes de cycle toujours visibles | Table scannable + **détail Cycle** en expand / Inspecteur |
| Cellules rouge/vert partout | Badge sévérité + tri par anomalie |
| Headers tronqués | Labels complets, colonnes essentielles |

---

## Layout

```
┌─ [Exceptions] [Carte] [Film] [Parc●] ───────────────────────┐
│ BARRE POSTE                                                 │
│ Onglets: [Équipements● | Conducteurs]                       │
│ Recherche [ID / nom]   Puces statut…                        │
├─────────────────────────────────────────────────────────────┤
│ TABLE (dense)                                               │
│ ID │ Statut │ Conducteur │ Gasoil │ NV │ Attente │ Idle │… │
│ 305│ Attente│ Bahar …    │ 54 l/h │  1 │  18m   │  4m │ ▸ │
│ 312│ Charge │ …          │ …      │  2 │   2m   │  0m │ ▸ │
│ …  tri défaut: Attente DESC                                 │
├─────────────────────────────────────────────────────────────┤
│ ▾ LIGNE EXPANDÉE — Cycle actuel (camion 305)                │
│ Vide │ Att. charge │ Charg. │ Chargé │ Att. déch. │ Déch.  │
│ 01:18│ 00:00       │ 01:34  │ 08:53! │ —          │ —      │
│ Durée cycle: 11:45  (moy. 09:20)  ↑                         │
│ [Slot IA] Pourquoi ce cycle est long ? — réservé            │
└─────────────────────────────────────────────────────────────┘
```

---

## Colonnes table (défaut)

1. Indicateur statut  
2. ID camion  
3. Conducteur (ou « ? » si inconnu — comme OPM)  
4. Gasoil (l/h)  
5. TD %  
6. TU %  
7. Heures de marche  
8. NV (voyages)  
9. Attente (agrégée)  
10. Idle  
11. Chevron expand  

**Arrêts (exploitation / matériel / extérieur / non défini)** → visibles en expand ou onglet Inspecteur « Arrêts », pas dans la grille principale.

---

## Onglet Conducteurs

Nom · Badge · Camion assigné · Statut · Cycles · Idle · Score (simple barre).

---

## Interactions

- Clic ligne → Inspecteur  
- Clic ▸ → expand cycle  
- Tri multi-colonnes  
- Double-clic ID → Inspecteur focus Cycle  

---

## États

| État | |
|---|---|
| Vide filtres | « Aucun équipement ne correspond. » |
| Chargement | squelette table |
| Erreur | bandeau + tableau figé dernière sync |

---

## Slot IA

Dans expand / Inspecteur : « Pourquoi ce cycle est long ? » + confiance + preuves (mock).
