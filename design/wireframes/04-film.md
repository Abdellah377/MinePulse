# WF-04 — Film (lo-fi gris) ★ ÉCRAN PRIORITAIRE

**Workspace :** Supervision › Film  
**Ancêtre OPM :** Film camion  
**Objectif :** reconstruire ce qui s'est passé (et se passe) par engin — outil d'investigation n°1.

---

## Utilisateur principal

Régulateur + chef de poste (analyse) ; ingénieur production (revue de poste).

---

## Ce qu'on garde d'OPM

- Une ligne = un équipement  
- Couleurs = états opérationnels  
- Hover = état, début, fin, durée  
- Sélection multi-engins (arbre)  
- Intervalle multi-postes possible  

## Ce qu'on change

- Panneau détail persistant (pas seulement hover)  
- Groupement + virtualisation pour 100+ engins  
- Zoom par presets (pas zoom libre chaotique)  
- Emphase « attentes / arrêts »  
- Slot IA Pourquoi dans le détail  
- Raccourcis clavier documentés  

---

## Layout 1920×1080

```
┌─ [Exceptions] [Carte] [Film●] [Parc] ───────────────────────┐
│ BARRE POSTE                                                 │
├─────────────────────────────────────────────────────────────┤
│ BARRE D'OUTILS                                              │
│ Poste [Matin ▾]  Type [Tous ▾]  Puces états  Recherche [ID] │
│ Grouper [Type▾]  Zoom [−][Poste|1h|15m][+]                  │
│ [Mettre en avant attentes/arrêts]                           │
├────────────┬────────────────────────────┬───────────────────┤
│ LIBELLÉS   │ PISTE TEMPORELLE           │ DÉTAIL            │
│ 220 sticky │ scroll X + Y               │ 360px             │
│            │                            │ (vide si aucune   │
│ ▾ Camions  │ 07  08  09  10  11  MAINT. │  sélection)       │
│  305  12v  │ ■■■□□■■■■■□□■■│            │                   │
│  312   9v  │ ■■□□□■■■■□□□□│            │                   │
│  …         │                            │                   │
│ ▸ Auxiliaires (6)  [replié]             │                   │
├────────────┴────────────────────────────┴───────────────────┤
│ LÉGENDE: Charge | Vide | Attente | Chargement | Arrêt | …   │
└─────────────────────────────────────────────────────────────┘
```

---

## États Film (légende — sémantique OPM adaptée)

| État | Usage |
|---|---|
| Mouvement à charge | Vert |
| Mouvement à vide | Jaune |
| Attente (charge / décharge) | Rouge / saumon |
| Chargement / Déchargement | Bleu |
| Arrêt / Arrêt à raison | Rouge foncé |
| Éteint | Bleu gris |
| Aucune donnée | Noir / hachures |
| Non déterminé | Gris |

*(En lo-fi : densités / hachures ; couleurs exactes en hi-fi.)*

---

## Règles de passage à l'échelle

1. Groupement défaut = **par type** ; Camions ouverts ; Auxiliaires fermés  
2. Hauteur de ligne dense ~28–32 px  
3. Sticky : libellés gauche, règle du temps, ligne MAINTENANT  
4. Presets zoom : **Poste entier** (défaut) · **1 h** · **15 min**  
5. « Mettre en avant attentes/arrêts » = atténue les autres segments (ne cache pas les lignes — conserve le pattern temporel)

---

## Interactions

| Action | Résultat |
|---|---|
| Hover segment | Tooltip : état · début–fin · durée · zone si connue |
| Clic segment | Panneau détail rempli |
| Clic libellé ligne | Résumé engin + mini film du poste |
| Double-clic ligne | Inspecteur |
| Collapse groupe | compteur + minutes d'attente agrégées |

### Raccourcis clavier (spec)

| Touche | Action |
|---|---|
| `/` | Focus recherche |
| `j` / `k` | Ligne suivante / précédente |
| `←` / `→` | Pan temporel |
| `1` `2` `3` | Zoom Poste / 1h / 15m |
| `Enter` | Ouvrir inspecteur |
| `Esc` | Désélection |

---

## Panneau détail (segment sélectionné)

```
État: Mouvement à vide
305 · 08:44:43 → 09:04:01 · 00:19:18
Zone: (si connue) Route vers Banc A

[Ouvrir équipement]

┌─ IA (réservé) ─────────────────────────┐
│ Raison probable: Attente chargeur      │
│ Confiance: 92% (mock)                  │
│ Preuves: aucun chargeur disponible…    │
│ [Désactivé — V1 prototype]             │
└────────────────────────────────────────┘
```

---

## Filtres (remplacent Paramètres OPM latéraux)

Site (topbar) · Poste / intervalle · Type · États · Recherche ID · Grouper · Emphase attentes

Arbre « Sélectionnés 21 de 22 » OPM → devient **filtre type + recherche** + compteur « N engins affichés ».

---

## États UI

| État | |
|---|---|
| Vide | « Aucun équipement pour ce site/poste. » |
| Recherche vide | « Aucun ID ne correspond. » |
| Chargement | règle + barres squelette |
| Erreur historique | bandeau + segments « Inconnu » hachurés |

---

## Anti-patterns (explicitement exclus)

- Création d'événements type MS Project  
- Flèches de dépendances entre camions  
- Zoom libre sans presets comme seul mode
