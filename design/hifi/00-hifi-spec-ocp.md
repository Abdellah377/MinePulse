# MinePulse — Specs haute-fidélité (OCP Light)

**Prérequis :** validation des wireframes lo-fi (`design/wireframes/`).  
**Livrable :** ce document = handoff hi-fi pour Figma. Peindre dans Figma dès que le quota MCP le permet.  
**Pas de code application.**

---

## 1. Tokens

| Token | Hex | Usage |
|---|---|---|
| `bg` | `#FFFFFF` | Fonds page / panneaux |
| `surface` | `#F4F6F5` | Rails, headers table, fond carte |
| `surface-2` | `#E9EEEC` | Hover / sélection |
| `border` | `#D0D8D4` | Traits 1 px |
| `text` | `#1C2421` | Texte principal |
| `muted` | `#5B6B64` | Labels secondaires |
| `ocp-green` | `#00843D` | Actions, onglet actif, LIVE |
| `ocp-green-soft` | `#E6F4EC` | Chip / fond sélection douce |
| `warning` | `#D97706` | Warning uniquement |
| `critical` | `#C0392B` | Critique / NOW Film |

### États Film / Carte / Parc

| État | Hex |
|---|---|
| Mouvement à charge | `#2E7D4F` |
| Mouvement à vide | `#C4A000` |
| Attente | `#C0392B` |
| Chargement / Déchargement | `#2F6FED` |
| Arrêt / Arrêt à raison | `#9B2C2C` |
| Éteint | `#5B7C99` |
| Aucune donnée | `#1C2421` |
| Non déterminé | `#8A9490` |

**Typo :** Inter · corps 12–13 · table 11 · titres 16–18 · chiffres tabulaires  
**Rayon :** 2–4 px max  
**Interdit :** glass, gradients décoratifs, dark mode, neon

---

## 2. Artboards Figma à créer (1920×1080)

| # | Nom | Source lo-fi |
|---|---|---|
| HF-01 | Supervision · Exceptions | `01-exceptions.md` |
| HF-02 | Supervision · Carte | `03-carte-zones.md` |
| HF-03 | Supervision · Carte · Éditeur zones | `03-carte-zones.md` |
| HF-04 | Supervision · Film | `04-film.md` |
| HF-05 | Supervision · Film · Segment sélectionné | `04-film.md` |
| HF-06 | Supervision · Parc | `02-parc.md` |
| HF-07 | Supervision · Parc · Cycle expand | `02-parc.md` |
| HF-08 | Événements | `05-evenements.md` |
| HF-09 | Inspecteur (overlay) | `06-inspecteur.md` |
| HF-10 | Fondations / tokens | ce fichier |

---

## 3. Chrome commun

- Sidebar 64 px : fond `surface`, item actif = barre gauche `ocp-green` + fond soft  
- Topbar 48 px : Site · Poste + progress · Recherche · LIVE (point vert) · cloche · user  
- Modes Supervision : underline 2 px vert sur actif  
- Barre poste 36 px : `surface`, texte dense  

---

## 4. Notes par écran (hi-fi)

### Exceptions
Liste 44 px/ligne ; point sévérité coloré ; zones à droite avec barre occupation (vert/orange/rouge selon seuil) ; Insights bas muted.

### Carte
Ortho/satellite autorisée (fidélité OPM ops). Marqueurs 8–10 px. Zones polygones semi-transparents + stroke. Mode édition : outils distincts, panneau propriétés type/couleur/description.

### Film
Lignes 28–32 px ; groupes `surface-2` ; segment colors ci-dessus ; détail 360 px ; slot IA bordure soft + label vert ; légende footer.

### Parc
Header table `surface` ; badges statut soft-fill ; expand cycle = stepper horizontal des étapes ; outlier = bordure warning/critical sur l'étape fautive seulement.

### Événements
Liste + détail ; workflow boutons ; slot IA toujours présent en bas du détail.

### Inspecteur
400 px ; tabs ; onglet IA placeholder.

---

## Fichiers Figma existants (référence)

- **Design pack (nouveau, shell) :** https://www.figma.com/design/lUILzCGorALnkErX8XTEAN  
- Lo-fi antérieur : https://www.figma.com/design/zqJwttAed6B5RJcy1to1Fw  
- Hi-fi shell : https://www.figma.com/design/EiDdOGQkYlJp6YHa5dV7Jq  

**Limitation :** plan Figma Starter (~6 appels MCP/mois). Les wireframes et specs hi-fi complets sont dans `design/` du repo — peindre manuellement dans Figma avec `hifi/00-hifi-spec-ocp.md`, ou demander « continue Figma hi-fi » après upgrade / reset quota.

---

## 6. Critères d'acceptation hi-fi

- [ ] Français partout  
- [ ] Vocabulaire cycle OPM respecté  
- [ ] Film = écran le plus travaillé  
- [ ] Zones éditables spécifiées  
- [ ] Slots IA visibles mais marqués non connectés  
- [ ] Aucun clone pixel d'OPM  
- [ ] Thème clair OCP uniquement  
