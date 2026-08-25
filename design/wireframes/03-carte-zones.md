# WF-03 — Carte + Éditeur de zones (lo-fi gris)

**Workspace :** Supervision › Carte  
**Ancêtre OPM :** Plan situation (CARTE)  
**Objectif :** où sont les engins et les zones opérationnelles — contexte spatial pour humains et IA future.

---

## Utilisateur principal

Régulateur / dispatcher.

---

## Layout mode Exploitation (défaut)

```
┌─ [Exceptions] [Carte●] [Film] [Parc] ───────────────────────┐
│ BARRE POSTE · LIVE                                          │
├──────────┬──────────────────────────────────┬───────────────┤
│ FILTRES  │     PLAN DE MINE                 │ INFO RAPIDE   │
│ 240px    │     (ortho / satellite OK)       │ 320px         │
│          │                                  │               │
│ Type     │  routes · polygones zones        │ ID / statut   │
│ Statut   │  marqueurs engins                │ vitesse/fuel  │
│ Couches  │                                  │ tâche         │
│ ☐ Stocks │  [+][-][⌂][calques][éditer]      │ zone actuelle │
│ ☑ Zones  │                                  │               │
│ ☑ Engins │                                  │ [Ouvrir détail│
│ Recherche│                                  │  / Éditer zone│
│          │  coords en bas à gauche          │               │
└──────────┴──────────────────────────────────┴───────────────┘
```

**Différence OPM :** pas d'étiquettes jaunes empilées — labels selon zoom ; calques on/off ; marqueurs engins lisibles.

---

## Layout mode Éditeur de zones

Basculé via bouton **Éditer les zones** (toolbar carte).

```
┌─ MODE ÉDITION ZONES ────────────────────────────────────────┐
│ Outils: [Sélection] [Polygone] [Éditer sommets] [Supprimer] │
├──────────┬──────────────────────────────────┬───────────────┤
│ LISTE    │     CANVAS + polygone en cours   │ PROPRIÉTÉS    │
│ ZONES    │                                  │               │
│ Charg. A │                                  │ Nom: [____]   │
│ Dump 2   │                                  │ Type: [▾]     │
│ Fuel     │                                  │ Couleur: [■]  │
│ Atelier  │                                  │ Description:  │
│ + Nouvelle│                                 │ [________]    │
│          │                                  │ [Enregistrer] │
│          │                                  │ [Annuler]     │
└──────────┴──────────────────────────────────┴───────────────┘
```

### Types de zone (obligatoires)

Chargement · Dump / Déchargement · Concasseur · Station fuel · Atelier · Parking · Zone restreinte

### Pourquoi pour l'IA (note produit)

Si camion 305 entre dans **Station fuel** → l'agent pourra dire « probablement en ravitaillement » plutôt que « arrêté ».

---

## Interactions Exploitation

| Action | Résultat |
|---|---|
| Clic engin | sélection + Info rapide |
| Double-clic / Ouvrir | Inspecteur |
| Clic zone | highlight + occupation |
| Pan / zoom | molette + boutons |
| Recherche ID | centre sur l'engin |

---

## Interactions Éditeur

Dessin polygone · édition sommets · assignation type/couleur · save mock (V1 local) · validation type requis.

---

## États

| État | |
|---|---|
| Vide filtres | plan visible + « Aucun engin ne correspond. » |
| Chargement | silhouette plan + points atténués |
| Erreur positions | bandeau « Positions éventuellement obsolètes » |

---

## Slots IA (placeholder)

Chips discrets sur carte ou dans Info rapide :
- Congestion détectée  
- Engin inutilisé  
- Trajet anormal  

Label « Aperçu IA — non connecté ».
