# WF-05 — Événements (lo-fi gris)

**Workspace :** Événements (nav principale)  
**Objectif :** triage unifié des alertes opérationnelles (OPM fragmenté / faible).

---

## Utilisateur principal

Chef de poste + régulateur sous pression.

---

## Types d'événements (exemples)

- Arrêt critique équipement  
- Anomalie gasoil  
- Perte de communication  
- Attente trop longue  
- Problème mécanique  
- Congestion de route  
- Cycle trop long  

---

## Layout

```
┌─ Événements ────────────────────────────────────────────────┐
│ Sévérité [Crit][Warn][Info]  Statut [Tous|Nouveau|…]  Cher. │
├──────────────────────────────────┬──────────────────────────┤
│ LISTE                            │ DÉTAIL                   │
│ ☐ ● Critique · Cam.305 · 2m     │ Titre                     │
│ ☐ ● Warning · Zone Banc B · 8m  │ Sévérité · Catégorie      │
│ ☐ ○ Info · Maintenance due      │ Description               │
│                                  │ Équipement → [ouvrir]     │
│                                  │ Localisation / zone       │
│                                  │ Horodatage                │
│                                  │ Statut workflow           │
│                                  │ Assigné à                 │
│                                  │                          │
│ [Résoudre sélection]             │ [Acquitter][Assigner][OK]│
│                                  │                          │
│                                  │ ┌─ IA (réservé) ───────┐ │
│                                  │ │ Explication          │ │
│                                  │ │ Impact production    │ │
│                                  │ │ Action recommandée   │ │
│                                  │ │ Priorité             │ │
│                                  │ └──────────────────────┘ │
└──────────────────────────────────┴──────────────────────────┘
```

---

## Champs obligatoires (détail)

| Champ | |
|---|---|
| Sévérité | critique / warning / info |
| Équipement | ID ou null (événement de zone) |
| Localisation | zone / coords texte |
| Horodatage | création + mise à jour |
| Statut | nouveau → acquitté → assigné → résolu |
| Assigné | utilisateur |
| Résolution | texte libre (mock) |

---

## Workflow

`Nouveau` → `Acquitté` → `Assigné` → `Résolu`  
Multi-sélection → résoudre en lot.

Cloche topbar = miroir des 5 non résolus.

---

## États

Vide / chargement squelette / erreur bandeau — standard.

---

## Slot IA

Toujours visible dans le détail, contenu mock :
- Explication  
- Impact  
- Action recommandée  
- Priorité  
- Impact production estimé  

Badge « Aperçu — non connecté ».
