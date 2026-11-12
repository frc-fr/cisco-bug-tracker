# cisco-bug-tracker

Site statique de suivi des bugs Cisco et de leurs corrections, construit à partir des Release Notes
publiques de Cisco : IOS, IOS XE, IOS XR, NX-OS, Secure Firewall ASA et Secure Firewall Threat
Defense (FTD), pour les gammes de routeurs, de commutateurs et de pare-feu.

Ce projet est indépendant. Il n'est pas affilié à Cisco Systems.
Les informations sont fournies à titre indicatif : vérifiez toujours la documentation officielle.

## Gammes suivies

| Système | Gammes |
|---|---|
| IOS XE | ISR 1000, ISR 4000, Catalyst 8200, 8300, 8500, 8000V, ASR 920, ASR 1000, Catalyst 9200, 9300, 9400, 9500, 9600, Catalyst 3850 (16.9 à 16.12) |
| IOS | Plateformes IOS 15 M&T (Cross Platform Release Notes 15.8(3)M, 15.9(3)M), Catalyst 2960-X, Catalyst 1000 |
| IOS XR | ASR 9000, NCS 540, NCS 560, NCS 5500, Cisco 8000 |
| NX-OS | Nexus 3000, Nexus 7000, Nexus 9000 (mode NX-OS) |
| ASA | Secure Firewall ASA (9.12 et suivantes) |
| FTD | Secure Firewall Threat Defense (6.4 et suivantes) |

La liste est dans `sources/catalog.json` : une page « Release Notes » par gamme, et pour chaque
adresse de note le système et la gamme qu'elle documente. Ajouter une gamme, c'est y ajouter sa page
et le motif de ses notes.

## Fonctionnalités

- Recherche par identifiant de bug (CSCwu11498) ou mots-clés, par version et par matériel
- Un onglet par système, chacun avec ses propres données
- Mise en avant des branches actives, sans masquer les autres
- Comparaison de deux versions : bugs corrigés, nouveaux problèmes ouverts, problèmes toujours
  présents, et sections de mise à niveau à lire dans les notes de la version cible
- Liste des modèles cités dans les titres des bugs
- Suivi des nouveautés, avec un flux RSS/Atom
- Interface en français et en anglais

Vos recherches et vos filtres restent dans votre navigateur : ils ne sont ni enregistrés ni transmis.

## Ce que disent les notes, et ce qu'elles ne disent pas

- Cisco publie une note par gamme, qui couvre une version (NX-OS 10.5(5)M) ou toutes les versions
  d'une branche (IOS XE 17.12.x). Elle liste une sélection de bugs ouverts et résolus par version. Le
  Bug Search Tool de Cisco en contient davantage, mais demande un compte : le site ne l'interroge pas.
- Une version de maintenance (17.12.4) contient les correctifs des versions précédentes de sa branche.
  Un rebuild (17.12.3a, 10.3(4a)M, 9.22(1.1), 7.4.2.1) ne suit que sa version de maintenance.
- La famille d'un bug est celle des notes qui le listent. Un modèle précis n'est connu que lorsque le
  titre du bug le cite. Le filtre matériel est donc inclusif : avec un modèle choisi, il garde les bugs
  qui le citent et ceux de sa famille qui ne citent aucun modèle.
- Dates de support : pour IOS XE, fin de maintenance, fin de support et branches LTS proviennent
  d'[endoflife.date](https://endoflife.date/cisco-ios-xe), qui les recense d'après les bulletins de
  Cisco. NX-OS : tableau du [Cisco NX-OS Software Lifecycle Support Statement](https://www.cisco.com/c/en/us/products/collateral/ios-nx-os-software/nx-os-software/guide_c07-658595.html).
  FTD : tableaux du [Secure Firewall Threat Defense Compatibility Guide](https://www.cisco.com/c/en/us/td/docs/security/secure-firewall/compatibility/threat-defense-compatibility.html),
  avec la dernière version FTD de chaque plateforme Firepower ou ASA arrêtée. IOS XR et ASA : annonces
  End-of-Sale and End-of-Life de leur page « EoS/EoL notices », chacune lue une fois. Une branche pas
  encore annoncée reste supportée, sans date. IOS : sans table publiée, une branche est dite active quand
  l'une de ses notes a été révisée dans les douze derniers mois. Le site le précise.
- Les avis de sécurité sont écartés et les références CVE retirées des titres.
- Certains tableaux ne disent pas assez pour être lus sans deviner : bugs d'une branche sans version
  nommée, tableau sans légende sous un titre « Resolved and Open Bugs », bug cité dans une section
  « Behavior Changes ». Ils sont écartés et listés dans le champ `left_out` de la note extraite. Tout
  autre tableau que l'extraction ne sait pas situer arrête la mise à jour.

## Sources

- Release Notes sur `www.cisco.com/c/en/us/td/docs/`, dont le robots.txt autorise les robots, comme
  les pages « Release Notes » de chaque gamme sous `/c/en/us/support/`. Les notes sont lues dans leur
  version HTML : leurs tableaux de bugs y sont structurés, et chaque bug renvoie à la page exacte qui le
  cite. Une note découpée en chapitres est suivie jusqu'aux chapitres de ses bugs.
- Les pages HTML n'ont ni ETag ni date de modification. Le PDF que Cisco génère à partir de chaque note
  en a une : une requête HEAD sur ce PDF indique si la note a changé, et seule une note modifiée est
  téléchargée à nouveau. Les notes inchangées depuis plus de 18 mois ne sont vérifiées qu'une fois par
  semaine. Deux secondes séparent deux requêtes.
- Dates de support d'IOS XE : API d'endoflife.date (`/api/v1/products/cisco-ios-xe`), dont le
  robots.txt autorise les robots, lue à chaque collecte et enregistrée dans `sources/lifecycle.json`.
  Si elle ne répond pas, les dernières dates sont gardées. Les pages Cisco (NX-OS, FTD, annonces IOS XR et
  ASA) sont lues à chaque collecte, dans le même fichier ; une page illisible garde ses dernières dates.
- Matériel : pages « EoS/EoL notice listing » des gammes suivies, listées dans `sources/hardware.json`
  avec leurs familles, relues une fois par semaine. Chaque bulletin « End-of-Sale and End-of-Life »
  matériel n'est lu qu'une fois : jalons « HW » (fin de vente, fin des versions de maintenance
  logicielle, fin de support) et références produit, enregistrés tels quels. Le build ne garde que les
  châssis (pas les pièces détachées `=`, offres Cisco ONE `C1-`, cartes, ventilateurs, alimentations).
  Cisco ne donne pas de dernière version logicielle par modèle : le statut suit la fin de maintenance
  logicielle. Toutes les gammes n'ont pas de bulletin publié.
- Le résultat de l'extraction est commité dans `data/` : vider le cache de la CI ne relance pas le
  téléchargement de toutes les notes.

## Mise à jour

Un traitement GitHub Actions est lancé du lundi au vendredi à 9 h 15, 14 h 15 et 19 h 00, heure de
Paris, et à la demande. Cet horaire est décrit dans `sources/schedule.yml`, que le site lit pour
l'afficher. Il collecte, extrait, contrôle, puis publie le site sur GitHub Pages. Si
un contrôle échoue, le site garde ses dernières données valides.

## Développement

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
node --test tests/site/logic.test.js
```

Pour récupérer les notes puis prévisualiser le site :

```sh
.venv/bin/ciscobugs collect
.venv/bin/ciscobugs extract
.venv/bin/ciscobugs --base-url http://localhost:8030/ build
python3 -m http.server 8030 --directory dist
```

## Licence

Le code est distribué sous licence [GNU AGPL 3.0 ou ultérieure](LICENSE).

Cette licence ne couvre pas les contenus de tiers, notamment les textes issus de la documentation
Cisco. Cisco, Cisco IOS, IOS XE, IOS XR, NX-OS, Catalyst, Nexus et Firepower sont des marques de Cisco
Systems, Inc. ou de ses filiales.

## Contact

Outil créé et maintenu par [FR Consulting](https://fr-consulting.fr).
Pour toute demande : contact@fr-consulting.fr
