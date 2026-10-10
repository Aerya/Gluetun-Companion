# Instructions permanentes pour les agents

## Documentation, versions et internationalisation

Pour chaque pull request, avant de la finaliser :

1. Déterminer si le changement est visible ou significatif pour les utilisateurs, opérateurs ou contributeurs.
2. Vérifier les fichiers de documentation réellement suivis par ce dépôt (notamment les `README*`, puis tout `CHANGELOG*`, notes de version, documentation sous `docs/` ou annonces existantes).
3. Mettre à jour uniquement les artefacts pertinents : les fonctionnalités, corrections significatives, changements de compatibilité et optimisations visibles doivent être documentés selon la pratique existante du dépôt. Ne pas créer de changelog, popup, système de release notes ou traduction parallèle lorsqu’il n’en existe pas.
4. Ne pas réaliser de nettoyage documentaire historique ni modifier de la documentation non liée à la PR.
5. Préserver les langues officiellement présentes dans les fichiers et le code concernés. Lorsqu’un mécanisme d’i18n/locales existe, l’utiliser : aucun nouveau texte utilisateur ne doit contourner ce mécanisme, les clés, paramètres, textes rendus, erreurs et notifications visibles doivent être vérifiés. Conserver le fallback défini par le projet et ne pas en inventer un autre.
6. Dans le résumé final de la PR, indiquer explicitement les vérifications effectuées et, pour chaque artefact non modifié, pourquoi sa mise à jour n’était pas nécessaire. En cas d’ambiguïté sur l’impact documentaire ou linguistique, demander confirmation à l’utilisateur avant de finaliser.

## Checklist de finalisation

- Code et tests adaptés au périmètre de la PR.
- Documentation pertinente vérifiée.
- Changelog, notes de version ou annonce existante vérifiés.
- Locales et textes visibles vérifiés quand le dépôt en possède.
- Absence de régression ou d’incohérence documentaire et linguistique.
