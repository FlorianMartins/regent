# Dossier de présentation — Regent

*Document en français destiné à un entretien pour un poste de Tech Lead / Architecte IA. Le reste de la documentation est en anglais.*

!!! tip "En clair"
    Regent est une plateforme qui met des agents d'IA au travail sur les tâches répétitives et risquées de la livraison logicielle (relire du code, comprendre pourquoi une chaîne d'intégration a échoué, corriger de l'infrastructure mal configurée, réagir à une alerte…), **sans jamais laisser un agent faire quelque chose que personne n'a autorisé**. Chaque agent travaille sous un *mandat* écrit, chaque résultat est contrôlé par un vérificateur indépendant avant toute action, et tout est consigné dans un registre infalsifiable.

## Pitch en 30 secondes

« Les équipes de développement perdent des heures sur des vérifications mécaniques, et les outils d'IA qu'elles adoptent une par une n'ont ni règles, ni traçabilité, ni contrôle des données. Regent est une plateforme d'agents IA *gouvernés* : six agents spécialisés (revue de PR, triage CI, correction d'infrastructure-as-code, triage d'incident, dépendances, notes de version) qui ne peuvent utiliser que les outils listés dans leur mandat, au niveau d'autonomie accordé, dans un budget, avec un vérificateur indépendant avant chaque action et un registre d'audit chaîné par hachage. C'est du code testé hors ligne, avec des évaluations, des attestations de chaîne d'approvisionnement et une documentation lisible par un non-spécialiste. »

## Le problème

1. **La latence de revue** : la première passe sur une pull request (bugs évidents, failles, tests manquants) est mécanique mais mobilise un senior.
2. **Le *toil* opérationnel** : builds relancés à l'aveugle, mises à jour de dépendances qui s'accumulent, findings de scanner acquittés puis oubliés, incidents où l'on cherche « ce qui a changé ».
3. **L'IA sans gouvernance** : un agent qui peut fusionner peut fusionner n'importe quoi ; un diff ou un log peut contenir une injection de prompt ; du code confidentiel part vers une API tierce ; personne ne peut répondre à l'auditeur.

## La solution

Un moteur d'exécution où **les agents agissent sous mandat** :

| Propriété | Mécanisme | Où dans le code |
|---|---|---|
| **Borné** | mandat YAML : niveau d'autonomie (L0 observer → L3 agir réversible ; L4 jamais accordé), liste blanche d'outils, budget, approbations, plafond de confidentialité | `policies/mandates/`, `regent/core/policy.py` |
| **Vérifié** | pipeline *analyser → vérifier → agir* : contrôles déterministes écrits en code + critique par un second appel modèle avec un prompt différent | `regent/runtime/runner.py`, `regent/agents/verifier.py` |
| **Traçable** | registre JSON Lines chaîné par SHA-256, vérifiable hors ligne (`regent ledger verify`) | `regent/core/ledger.py` |
| **Confidentiel** | classification des données (PUBLIC → RESTRICTED), rédaction des secrets avant chaque appel, routage vers un modèle local au-delà du plafond | `regent/gateway/` |

## Les cinq décisions d'architecture clés

1. **L'autonomie est une configuration, pas du code** (ADR-0001). Le même agent tourne en « conseil » sur un dépôt et en « action réversible » sur un autre ; élargir un mandat est une pull request relue par la sécurité, visible dans le registre.
2. **Analyser → vérifier → agir, avec un critique indépendant** (ADR-0002, 0011). Aucune écriture pendant l'analyse (barrière de phase) ; aucune action sans accord du critique *et* des contrôles déterministes. Séparation des pouvoirs appliquée aux modèles.
3. **Pas de framework d'agents** (ADR-0003). ~1 500 lignes de runtime maison : chaque point de décision est une fonction testée, pas un callback caché. Les intégrations sont volontairement peu nombreuses.
4. **Une seule porte vers les modèles** (ADR-0004, 0005, 0012). Rédaction, classification, routage par *tier* (rapide / équilibré / profond) et non par nom de modèle, budget, audit : les agents ne peuvent pas contourner un contrôle, même par erreur.
5. **Le scanner est la vérité, pas le modèle** (ADR-0013). Le correctif d'infrastructure proposé par le modèle est réécrit dans l'espace de travail et **re-scanné par CloudGuard-IaC** avant qu'une PR brouillon ne soit ouverte. Le modèle ne note jamais sa propre copie.

## Ce que le dépôt prouve

| Preuve | Détail |
|---|---|
| **117 tests** automatisés, hors ligne | Aucun secret, aucun réseau : le modèle est remplacé par un fournisseur *replay* (réponses scriptées), GitHub par un faux client. Les propriétés de sûreté sont des tests : outil hors liste blanche refusé, écriture pendant l'analyse refusée, rejet du vérificateur bloquant, registre falsifié détecté, budget dépassé, approbation requise puis accordée. |
| **6 cas d'évaluation** (`evals/cases/`) | Les prompts sont testés comme du code, y compris un cas d'**injection de prompt** dans un diff. Mode `--live` nocturne sur le vrai modèle. |
| **6 agents + 1 vérificateur**, **31 outils** avec classe de risque déclarée | 16 outils GitHub, 10 commandes en bac à sable (liste blanche, sans shell), CloudGuard, système de fichiers cloisonné, PromQL. |
| **16 ADR** | Chaque décision avec son contexte, ses alternatives et ses conséquences. |
| **9 runbooks** | Kill switch, agent défaillant, budget, vérification du registre, rotation des secrets, approbation, onboarding, ajout d'agent, changement de mandat. |
| **Qualité** | `ruff`, `mypy --strict`, `bandit`, `pip-audit`, couverture ≥ 80 % exigée, CI en 9 portes. |
| **Chaîne d'approvisionnement** | SBOM (Syft), scan Trivy, provenance SLSA attestée, signature *keyless* cosign, Scorecard OpenSSF, CodeQL, Dependabot — vérifiables par n'importe qui avec une commande. |
| **Filiation** | Construit sur [CloudGuard-IaC](https://github.com/FlorianMartins/cloudguard-iac) (scanner shift-left, 31 règles) et le [LLM Security Lab](https://github.com/FlorianMartins/hivey-llm-security-lab) (OWASP LLM Top 10). |

## Limites assumées

- **Les approbations se font par ré-exécution** (ADR-0010) : pas de processus suspendu. Suffisant pour des agents en une passe ; Temporal est prévu quand des runs devront attendre des heures.
- **Index des runs en mémoire** dans le plan de contrôle (ADR-0009) ; Postgres en production. Le registre reste la source de vérité.
- **Le registre est infalsifiable en évidence, pas indestructible** : il doit être expédié vers un stockage à écriture unique.
- **Le critique est un juge LLM** avec les biais d'un LLM ; c'est pourquoi il n'est jamais la seule barrière (contrôles déterministes, mandat, humain).
- **SLSA niveau 2 visé**, pas 3 : le niveau 3 demande des builds isolés non réutilisables ; prévu quand la cadence de release sera stable.
- **Six workflows**, pas un assistant général : c'est un choix, pas un manque.

## Feuille de route

1. **Phase 1 — dans la CI** : `regent run …` dans les jobs GitHub Actions, identité du job, registre en artefact. Valeur dès la première semaine.
2. **Phase 2 — plan de contrôle** : API FastAPI (webhooks GitHub et Alertmanager, approbations), Kubernetes/Argo CD, Postgres.
3. **Phase 3** : Temporal (exécution durable), portail Backstage, modèles locaux systématiques pour le RESTRICTED, jeux de données « or » construits à partir des findings rejetés.

## Dix questions probables en entretien

1. **Pourquoi ne pas utiliser LangChain ou un framework d'agents ?** Parce qu'une plateforme gouvernée doit rendre chaque point de décision lisible et testable ; un tool-loop caché dans un framework est exactement la surface qu'on ne peut pas auditer. Le runtime fait ~1 500 lignes.
2. **Comment empêchez-vous l'injection de prompt ?** Trois couches : les données externes sont balisées `<untrusted_data>` et les prompts disent qu'elles ne sont jamais des instructions ; les outils sont en liste blanche (une instruction injectée « fusionne » n'a pas d'outil à appeler) ; le vérificateur relit la sortie comme une donnée. Un cas d'éval le teste.
3. **Et si le modèle se trompe ?** Les sorties sont structurées et portent des preuves ; des contrôles déterministes en code (le finding cite une ligne du diff, le correctif passe le scanner) rejettent avant le critique ; le mandat borne les conséquences ; un humain fusionne.
4. **Comment gérez-vous la confidentialité ?** Chaque résultat d'outil a une classe ; la classe d'un run ne fait que monter ; au-delà du plafond du mandat, la passerelle route vers un modèle local ou échoue *fermé*. Les secrets sont rédigés avant tout appel.
5. **Qu'est-ce qui empêche un agent de supprimer quelque chose ?** Aucun outil `DESTRUCTIVE` n'existe ; en ajouter un est une décision d'architecture visible ; et la classe exige L4, qu'aucun mandat n'accorde (`policy-check` le refuse).
6. **Comment faites-vous évoluer un prompt sans casser la prod ?** Prompt versionné (`pr_reviewer@1` → `@2`), sha256 dans le registre, cas d'éval obligatoire, suite hors ligne à chaque push, suite *live* la nuit, taux de rejet du vérificateur surveillé après déploiement.
7. **Combien ça coûte ?** Budget dur par run dans le mandat (appels, jetons, dollars, secondes), tiers dégradés sous 10 centimes restants, cache du prompt système, métrique `regent_llm_usd_total` par agent et modèle. Estimation documentée avec hypothèses explicites (~140 USD/mois pour un volume moyen).
8. **Comment un auditeur vérifie-t-il ?** `regent ledger verify` re-hache la chaîne ; chaque décision porte la règle qui a tranché ; chaque approbation porte un nom ; `gh attestation verify` et `cosign verify` prouvent l'origine des artefacts.
9. **Pourquoi commencer dans la CI plutôt que par un service ?** Parce que les événements (PR, build, release) y ont déjà une identité, un checkout et des secrets ; zéro infrastructure nouvelle pour la première valeur. Le plan de contrôle vient pour les alertes et les approbations par API.
10. **Quelle est la première chose que vous feriez en arrivant dans une entreprise ?** Un dépôt pilote en L0/L1 avec le registre expédié au SIEM, deux semaines de mesures (taux d'acceptation, taux de rejet, coût), puis une montée d'autonomie par agent, par dépôt, avec les chiffres.
