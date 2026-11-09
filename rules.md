---
type: Project Rules
title: Règles de cisco-bug-tracker
description: Règles communes aux bug trackers et particularités des systèmes Cisco.
resource: https://github.com/frc-fr/cisco-bug-tracker
tags: [rules, cisco, ios, ios-xe, ios-xr, nx-os, asa, ftd, bug-tracker]
timestamp: 2026-11-09T19:00:00+01:00
product: IOS, IOS XE, IOS XR, NX-OS, Secure Firewall ASA, Secure Firewall Threat Defense
site: https://frc-fr.github.io/cisco-bug-tracker/
---

# Critères communs

Section identique dans forti-, juni-, palo- et cisco-bug-tracker. Toute modification se reporte dans les quatre.

## Architecture

- Site statique : pas de serveur, pas de base de données.
- Python côté collecte, JavaScript sans framework côté navigateur.
- Paquet Python `<fournisseur>bugs`, une commande par étape :
  - `collect` : met à jour l'état des sources et télécharge ce qui a changé.
  - `extract` : lit les documents en cache ; échoue au moindre avertissement.
  - `build` : croise les données et génère `dist/`.
- Modules : `collect`, `parser`, `extract`, `normalize` (matériel), `lifecycle` (dates de support), `build`, `feed`, `cli`.

### Répertoires

- `sources/` : état des sources (adresses, ETag, lastmod, dates de support). Commité.
- `.cache/` : documents bruts. Non versionné, gardé par le cache de la CI.
- `data/extracted/` : un JSON par document, une ligne par bug pour des diffs lisibles. Commité.
- `data/changes.json` : journal des nouveautés. Absent au départ : la première extraction sert de référence.
- `site/` : `index.html`, `app.js` (affichage), `logic.js` (règles de statut, testables), `i18n.js`, `theme.js`, `style.css`, mentions légales FR/EN.
- `dist/` : site généré, avec `data/*.json` compacts et `feed.xml`. Non versionné.

### Modèle de données

- Un bug = identifiant, description, contournement, matériel cité, événements.
- Un événement = version, statut (`r` corrigé, `k` connu, `l` limitation…), page officielle.
- Les statuts par version sont calculés dans le navigateur, à partir des notes de la branche.

### Tests

- `pytest` : tests unitaires, plus tests sur les vrais documents en cache.
- `node --test tests/site/logic.test.js` : règles de statut et de comparaison.
- Test des clés de traduction et de la CSP.

## Sources et collecte

- Sources officielles et publiques du fournisseur en priorité.
- Source communautaire (ex. endoflife.date) seulement à défaut d'équivalent officiel, citée comme telle dans les mentions légales.
- robots.txt respecté : un chemin interdit n'est jamais interrogé.
- 2 secondes minimum entre deux requêtes, User-Agent du projet.
- Ne recharger que ce qui a changé (ETag, Last-Modified, lastmod du sitemap).
- Résultats d'extraction commités dans `data/` : vider le cache CI ne relance pas tout.
- Un avertissement d'extraction arrête la mise à jour : le site garde ses dernières données valides.
- Une source annexe (dates de support…) en échec garde ses dernières valeurs.
- Le navigateur ne contacte jamais de service tiers.

## Contenu

- Objet : bugs connus et bugs corrigés. Jamais la sécurité.
- Entrées de sécurité écartées, références CVE retirées des descriptions.
- Chaque fait renvoie à la page officielle exacte qui le porte.
- Textes des bugs laissés en anglais, tels que publiés.
- Statuts déduits des notes, jamais inventés ; « Inconnu » expliqué et masqué par défaut.
- Un modèle cité ne veut pas dire « seul ce modèle est touché ». Filtre matériel inclusif.
- Un bug à la fois correction et changement de comportement n'est compté qu'une fois.
- Une version annoncée mais pas encore publiée est marquée « non publiée ».
- Toutes les branches restent consultables ; les branches supportées sont mises en avant.
- Pas d'affirmation générale ou trop assurée dans les textes.

## Interface

- Français et anglais, sans page /en/ séparée.
- Bandeau visible : « vos sélections ne sont ni enregistrées ni transmises ».
- Onglets : Rechercher, Comparer, Matériel, puis Quoi de neuf à droite de Matériel.
- Comparaison : pastilles triées par ordre alphabétique, « Tous » en premier.
- Libellé court « Correction » ; risques (nouveaux, toujours présents) mis en valeur.
- Panneau « À lire » replié par défaut, il ne s'ouvre que si l'utilisateur le déplie.
- Listes déroulantes filtrables à la frappe ; bouton Réinitialiser.
- Tableau sélectionnable en entier et bouton « Copier le tableau ».
- Bouton de retour en haut de page.
- Logos RSS puis GitHub, minimalistes et presque transparents, à gauche de « EN ».
- Thème clair et sombre ; pas de noir trop profond.
- Textes longs justifiés, sur toute la largeur.
- Cron et date de dernière mise à jour affichés.
- Placeholders neutres : ne jamais révéler le matériel de l'utilisateur.

## Design

- Même structure et mêmes jetons de couleur dans les trois sites.
- Couleur du fournisseur en touche seulement : bordure haute et nom du produit.
- Contraste professionnel, rien qui « pique les yeux ».
- Cohérence entre pages : mêmes pastilles partout, pas de tuiles géantes.

## Publication

- Cron du lundi au vendredi : 9 h 15, 14 h 15, 19 h 00, Europe/Paris.
- Horaire décrit dans `sources/schedule.yml` et affiché sur le site, qui le lit au build.
- Workflow GitHub sans déclencheur `schedule` (retardé ou oublié par GitHub) : lancé par `workflow_dispatch`.
- Ordre : tests, collecte, extraction, tests sur le corpus réel, commit des données, build, GitHub Pages.
- Flux RSS/Atom des nouveautés.
- CSP stricte : aucun script, style ou service tiers.

## Mentions et licence

- Outil créé et maintenu par FR Consulting ; contact@fr-consulting.fr ; lien vers fr-consulting.fr.
- Site indépendant, non affilié au fournisseur. Jamais « approuvé par ».
- Mentions légales FR et EN, avec la liste des services et composants tiers.
- Code sous AGPL 3.0 ou ultérieure ; contenus du fournisseur exclus.
- README générique : rien de sensible ni de personnel.

# Particularités Cisco

## Six systèmes

- IOS, IOS XE, IOS XR, NX-OS, ASA, FTD : un onglet et des données par système.
- Gammes Routeurs, Switch et Firewall, listées dans `sources/catalog.json`.
- Ajouter une gamme : ajouter sa page « Release Notes » et le motif de ses notes au catalogue.
- Une note peut couvrir plusieurs gammes ; une version peut être décrite par plusieurs notes.

## Versions

- Un format par système, toujours lu comme branche, maintenance, rebuild :

| Système | Exemple | Branche | Rebuild |
|---|---|---|---|
| IOS | `15.9(3)M13`, `15.9(3)M0a` | `15.9(3)M` | lettre |
| IOS XE | `17.12.3a` | `17.12` | lettre |
| IOS XR | `7.11.21` | `7.11` | 3e chiffre : rebuild de `7.11.2` |
| NX-OS | `10.5(5)M`, `10.3(4a)M` | `10.5` | lettre |
| ASA | `9.22(1.1)` | `9.22` | interim |
| FTD | `7.4.2.1` | `7.4` | patch |

- Une maintenance porte les corrections des maintenances précédentes de sa branche.
- Un rebuild ne suit que sa maintenance : `17.12.3a` vaut pour `17.12.3b`, rien ne dit pour `17.12.4`.
- Même logique que les -S de Junos et les -h de PAN-OS.

## Sources

- Pages HTML sur www.cisco.com/c/en/us/td/docs/, autorisées par robots.txt.
- Nouvelles notes trouvées sur la page « Release Notes » de chaque gamme (`/c/en/us/support/`).
- Note en « livre » : suivie jusqu'aux chapitres qui contiennent des bugs.
- Pages HTML sans ETag ni Last-Modified : HEAD sur le PDF généré de la note pour savoir si elle a changé.
- Note inchangée depuis plus de 18 mois : vérifiée une fois par semaine.
- Bug Search Tool jamais interrogé : il demande un compte.
- Dates de support : endoflife.date pour IOS XE seulement (fin de maintenance, fin de support, LTS).
- Autres systèmes : pas de table Cisco unique. Branche « active » si une note a été révisée dans les 12 derniers mois, et le site le précise.

## Extraction

- Les notes ne listent qu'une sélection de bugs ouverts et résolus : le site le dit.
- Un tableau = un bug par ligne, identifiant `CSCwu11498` et titre.
- Le titre de section donne la version ; la légende du tableau donne le statut.
- Bugs d'une branche sans version nommée : écartés et signalés dans `warnings`.
- Avis de sécurité écartés, CVE retirées des titres.

## Matériel

- Famille d'un bug = famille des notes qui le listent : fiable.
- Modèle connu seulement quand le titre du bug le cite.

## Affichage

- Identifiants Cisco complets (`CSCwu11498`).
- Comparaison : sections de mise à niveau des notes de la version cible.
- Couleur de marque : bleu Cisco.

# Citations

[1] [robots.txt de www.cisco.com](https://www.cisco.com/robots.txt)
[2] [endoflife.date Cisco IOS XE](https://endoflife.date/cisco-ios-xe)
