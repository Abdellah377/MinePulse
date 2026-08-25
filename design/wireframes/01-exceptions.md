# WF-01 — Exceptions (lo-fi gris)

**Workspace :** Supervision › Exceptions  
**Objectif :** répondre en &lt; 5 s à « Qu'est-ce qui demande mon attention ? »  
**Pas de graphiques.** Pas de cards KPI géantes.

---

## Utilisateur principal

Chef de poste (secondaire : régulateur en début de poste).

---

## Hiérarchie d'information

1. Barre de poste (persistante)
2. Liste d'exceptions (primaire)
3. Zones en tension
4. Raccourcis vers Carte / Film / Événements
5. Bandeau Insights IA (réservé, 1 ligne)

---

## Layout 1920×1080 (gris)

```
┌─ chrome MinePulse ──────────────────────────────────────────┐
│ [Exceptions●] [Carte] [Film] [Parc]                         │
├─────────────────────────────────────────────────────────────┤
│ BARRE POSTE                                                 │
│ Poste matin · 04:12 restant · 68% objectif · 3 critiques    │
├──────────────────────────────┬──────────────────────────────┤
│ EXCEPTIONS (60%)             │ ZONES EN TENSION (40%)       │
│ Filtres: [Crit][Warn][Tous]  │                              │
│                              │ Banc B · file 7/3            │
│ ● Camion 305 · Attente 18m   │ Concasseur · retard 12m      │
│ ● Camion 312 · Cycle long    │                              │
│ ● Excav. 03 · Arrêt matériel │ RACCOURCIS                   │
│ ● Camion 211 · Gasoil bas    │ [Carte · Attentes]           │
│ …                            │ [Film · Arrêts]              │
│                              │ [Événements]                 │
├──────────────────────────────┴──────────────────────────────┤
│ INSIGHTS (réservé) — « Slot IA — non actif en V1 »          │
└─────────────────────────────────────────────────────────────┘
```

---

## Composants

| Élément | Comportement |
|---|---|
| Ligne exception | clic → Film ou Carte focus, ou Inspecteur |
| Zone | clic → Carte zone sélectionnée |
| Raccourcis | appliquent des pré-filtres |

---

## Filtres

Sévérité uniquement (site/poste = topbar).

---

## États

| État | Contenu |
|---|---|
| Vide | « Aucune exception ouverte pour ce poste. » + liens Carte/Film |
| Chargement | squelettes de lignes |
| Erreur | bandeau « Flux live indisponible. Dernière sync HH:MM. » |

---

## Slot IA (placeholder)

Bandeau bas : résumé de poste mocké (ex. « Production −7 % — cause probable : attentes chargement +23 %. »). Non cliquable en V1, ou ouvre un panneau « Aperçu » figé.
