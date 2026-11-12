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

Section identique dans forti-, juni-, palo-, cisco- et f5-bug-tracker. Toute modification se reporte dans les cinq.

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
- Même forme dans tous les sites, quelle que soit la façon de présenter du fournisseur : on cherche au même endroit.
- Données uniformes entre fournisseurs : pas d'information propre à un seul fournisseur si elle n'aide pas l'exploitation (ex. date de mise en vente).
- Plusieurs systèmes : sélecteur de logiciel, libellé visible « Logiciel », jamais un choix de matériel.

## Matériel et nouveautés

- Onglet Matériel : pastilles de statut (« Tous » en premier, puis « Plus dans la dernière branche » ou son équivalent).
- Colonnes : Modèle, Première version, Dernière version, Statut <logiciel>, Version recommandée, Fin de support.
- Statut tiré d'une source officielle du fournisseur : il dit, sans le deviner, si le matériel est encore maintenu.
- Fin de vie annoncée par référence : variantes affichées séparément, pièces détachées et modules écartés.
- Pas de source : « Aucune fin annoncée », jamais « supporté ».
- Version recommandée seulement si le fournisseur la publie sans compte ; sinon la colonne est absente, et la note dit pourquoi.
- Rechercher : un modèle choisi affiche ce que le fournisseur dit de lui (statut, version recommandée, fin de support).
- Quoi de neuf : cartes « Dernière version publiée », « Dernier document mis à jour », puis « Recommandée par <fournisseur> » si elle existe.

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
- Le sélecteur choisit un logiciel, jamais un matériel : libellé visible « Logiciel », nom complet en infobulle.
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
- Dates de support IOS XE : endoflife.date (fin de maintenance, fin de support, LTS).
- NX-OS : tableau du Cisco NX-OS Software Lifecycle Support Statement (EoSWM, EoVSS/LDoS ; la plus tardive des deux dates).
- FTD : tableaux du Threat Defense Compatibility Guide ; dernière version FTD par plateforme Firepower/ASA (« Arrêt après »).
- IOS XR, ASA : annonces End-of-Sale and End-of-Life de leur page « EoS/EoL notices », chacune lue une fois.
- Liste d'annonces : une branche non annoncée reste supportée sans date, sauf si elle est plus ancienne que toutes les annoncées.
- Lignes de modules (« Firepower 9300: SM-24… ») ignorées : le châssis continue avec d'autres modules.
- IOS : pas de table Cisco. Branche « active » si une note a été révisée dans les 12 derniers mois, et le site le précise.

## Extraction

- Les notes ne listent qu'une sélection de bugs ouverts et résolus : le site le dit.
- Un tableau = un bug par ligne, identifiant `CSCwu11498` et titre.
- Le titre de section donne la version ; la légende du tableau donne le statut.
- Bugs d'une branche sans version nommée : écartés et signalés dans `warnings`.
- Avis de sécurité écartés, CVE retirées des titres.

## Matériel

- Famille d'un bug = famille des notes qui le listent : fiable.
- Modèle connu seulement quand le titre du bug le cite.
- Fin de vie : bulletins End-of-Sale and End-of-Life des pages « EoS/EoL notice listing » de chaque gamme (`sources/hardware.json`).
- Un bulletin est lu une fois ; ses références sont gardées entières, le build choisit les châssis.
- Écartés : pièces `=`, Cisco ONE `C1-`, cartes, modules, ventilateurs, alimentations, licences, bulletins logiciels (« OS SW »).
- Pas de dernière version logicielle chez Cisco : statut = fin des versions de maintenance logicielle, puis Last Date of Support.
- Un châssis est rangé sous le modèle cité qui le préfixe (C9300-24T sous C9300) ; sinon il est son propre modèle.
- Gamme sans bulletin publié : « Aucune fin annoncée », jamais « supporté ».
- Pas de version recommandée : Cisco ne la publie pas sans compte.

## Affichage

- Identifiants Cisco complets (`CSCwu11498`).
- Comparaison : sections de mise à niveau des notes de la version cible.
- Couleur de marque : bleu Cisco.

# Citations

[1] [robots.txt de www.cisco.com](https://www.cisco.com/robots.txt)
[2] [endoflife.date Cisco IOS XE](https://endoflife.date/cisco-ios-xe)
