# Bench Monitoring RCE

Mini-projet autonome pour comparer et monitorer deux stratégies d'insertion en base:

- `ETL`: renumérotation en Python puis insertion dans les tables cibles.
- `ELT`: chargement brut dans une table de staging temporaire puis transformation SQL.

## Cible PostgreSQL

La base contient uniquement les 4 tables métiers:

- `tmp_des`
- `tmp_fix`
- `tmp_var`
- `tmp_seuil`

Les partitions et les séquences métier sont conservées. Il n'y a pas de schéma applicatif.

## Arborescence

- `configs/` : variables d'environnement et configuration de logs.
- `data/` : jeu de données de benchmark.
- `logs/` : fichiers de logs.
- `sql/` : script d'initialisation PostgreSQL.
- `src/bench_monitoring/` : code Python du mini-projet.

## Installation

```bash
cd /home/nico/bench_monitoring
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Initialisation de la base

Exécuter `sql/init_db.sql` sur la base PostgreSQL dédiée.

## Exécution

Générer le fichier de test:

```bash
bench-monitor-generate
```

Générer un fichier plus petit ou plus gros:

```bash
bench-monitor-generate --out data/flux_des_fix_var.dat --nb-des 100 --min-fix-per-des 5 --max-fix-per-des 20 --min-var-per-fix 1 --max-var-per-fix 10 --seed 123
```

Lancer le benchmark avec monitoring:

```bash
bench-monitor-run --cmd "bench-monitor-etl" --app bench-etl --out ./results/etl
bench-monitor-run --cmd "bench-monitor-elt" --app bench-elt --out ./results/elt
```

Profils disponibles:

```bash
bench-monitor-etl --profile baseline
bench-monitor-etl --profile copy
bench-monitor-etl --profile batch
bench-monitor-elt --profile baseline
bench-monitor-elt --profile memory
bench-monitor-elt --profile analyze
bench-monitor-elt --profile constraints
bench-monitor-elt --profile max
bench-monitor-elt --profile batch
```

**Modes d'optimisation**

- **ETL - baseline :** Charge chaque ligne source et l'insère immédiatement dans la table cible correspondante, sans écriture intermédiaire en CSV ni regroupement par lots. C'est le mode le plus naïf, utile comme point de comparaison.
- **ETL - copy :** Chemin rapide utilisant la commande PostgreSQL `COPY` pour charger des CSV produits par l'étape de parsing ETL. Les CSV sont écrits sur disque puis streamés vers la base par blocs, ce qui limite la mémoire côté client. Adapté aux gros jeux de données si la base supporte le chargement massif.
- **ETL - batch :** Charge les CSV en mémoire par lots puis effectue des `INSERT` via `executemany` avec une taille de lot configurable. Utilise un peu plus de mémoire côté client mais permet de comparer le coût CPU/BD des INSERTs batchés vs COPY. Contrôlé par `ETL_PROFILES['batch'].batch_size`.

- **ELT - baseline :** Flux ELT simple : on stream le fichier brut dans une table de staging par blocs tamponnés, puis on transforme en SQL. Réglages de session minimaux ; profil de référence à faible risque.
- **ELT - memory :** Augmente les paramètres mémoire côté serveur (`work_mem`, `temp_buffers`, `maintenance_work_mem`) pour favoriser les opérations en mémoire pendant la transformation. À utiliser si le serveur dispose de RAM suffisante pour réduire les I/O sur fichiers temporaires.
- **ELT - analyze :** Exécute `ANALYZE` sur les objets temporaires après le `COPY` pour fournir de meilleures statistiques au planificateur SQL avant les transformations lourdes.
- **ELT - constraints :** Tente de désactiver temporairement les triggers/contraintes sur les tables cibles pendant le chargement pour accélérer l'insertion. L'agent vérifie les privilèges ; si l'opération n'est pas permise le profil poursuit sans cette optimisation et journalise la situation.
- **ELT - max :** Combine plusieurs optimisations (réglages mémoire, `ANALYZE`, désactivation de contraintes, `COPY ... FREEZE`, `synchronous_commit` off, `jit` off) pour un run très performant mais gourmand en ressources.
- **ELT - batch :** Reproduit la sémantique `batch` côté ETL : le client groupe les lignes selon `batch_size` puis écrit des blocs plus gros dans le flux `COPY`. Permet une comparaison équitable ETL vs ELT en mode batch.

**Notes sur la mémoire et la sécurité**

- **Mémoire client vs serveur :** Les optimisations réduisent le buffering côté client (les lectures/écritures sont streamées), mais les paramètres et opérations côté serveur (`work_mem`, `temp_buffers`, `maintenance_work_mem`, opérations internes) peuvent toujours consommer beaucoup de mémoire. Mesure le RSS client et serveur lors des ajustements.
- **Swap :** Le streaming réduit la probabilité d'OOM, mais sur de petites instances EC2 un petit swap (ex. 1–2 GiB) reste une sécurité pragmatique pour éviter des kills immédiats en cas de pics inattendus.
- **Mesurer avant de modifier l'infra :** Utilise `/usr/bin/time -v` pour capturer le pic RSS lors d'une génération / ETL / ELT. Exemple :

```bash
/usr/bin/time -v python3 -m bench_monitoring.generate_data_set --out data/flux.dat --nb-des 10000
/usr/bin/time -v python3 -m bench_monitoring.etl --profile copy
/usr/bin/time -v python3 -m bench_monitoring.elt --profile batch
```

**Fichiers et code**

- ETL streaming et gestion CSV : [src/bench_monitoring/etl.py](src/bench_monitoring/etl.py)
- ELT streaming et staging : [src/bench_monitoring/elt.py](src/bench_monitoring/elt.py)
- Génération tamponnée (flush côté client) : [src/bench_monitoring/generate_data_set.py](src/bench_monitoring/generate_data_set.py)

Si tu veux, je peux aussi ajouter des options CLI pour régler `batch_size`/`batch_mb` à l'exécution et un petit utilitaire qui lance un test profilé en mémoire et écrit un rapport dans `results/`.

Le profil `max` combine les optimisations cohérentes testées côté ELT: mémoire temporaire, `ANALYZE`, copie `FREEZE`, et désactivation temporaire des triggers de contraintes sur les tables cibles.

L'infrastructure AWS actuelle cible PostgreSQL 16.14 sur RDS, avec un parameter group dédié qui active `track_io_timing` et `track_wal_io_timing` pour rendre exploitables les métriques I/O par exécution.

Lancer une série complète sur plusieurs volumes de données:

```bash
bench-monitor-series --nb-des 30 100 300 --results-root ./results/series --data-root ./data/generated
```

Chaque volume génère son dataset, puis enchaîne ETL et ELT avec le même fichier d'entrée.

Lancer plusieurs réplications par volume pour lisser le bruit:

```bash
bench-monitor-series --nb-des 30 100 300 --replications 3 --results-root ./results/series --data-root ./data/generated
```

Chaque réplication utilise une graine différente mais reproductible, et les résultats sont rangés par volume puis par réplication.

Par défaut, la fin de `bench-monitor-series` crée une archive `.tar.gz` du répertoire de résultats de la série, supprime l'objet S3 cible s'il existe déjà, puis l'envoie vers le bucket `my-tfstate-project1-nicode-202506`.

```bash
bench-monitor-series --nb-des 30 100 300 --results-root ./results/series --data-root ./data/generated --s3-bucket my-tfstate-project1-nicode-202506
```

Si tu veux désactiver l'envoi S3, ajoute `--skip-s3-upload`.

Pour écrire et écraser un fichier dans S3 avec cette approche, le droit IAM minimal est `s3:PutObject` sur la clé cible, et `s3:DeleteObject` si tu veux supprimer explicitement l'objet avant de le réécrire. `s3:ListBucket` n'est utile que si tu veux lister ou vérifier l'existence avant upload.

Pour comparer plusieurs variantes sur les mêmes données:

```bash
bench-monitor-series --nb-des 30 100 300 500 1000 1500 2000 --replications 5 --etl-profiles baseline copy batch --elt-profiles baseline memory analyze constraints max batch --results-root ./results/series --data-root ./data/generated
```

Le monitoring capture aussi les compteurs PostgreSQL utiles à l'analyse, dont `pg_stat_wal` pour estimer le volume de WAL généré pendant chaque run.

Pour chaque exécution, le monitor enregistre un snapshot de début et de fin afin de calculer les deltas de `pg_stat_io`, `pg_stat_bgwriter`, `pg_stat_database` (dont les fichiers/bytes temporaires) et `pg_stat_wal` sur le run courant.

## Variables d'environnement

Editer le fichier `.env` et renseigner les paramètres PostgreSQL.

## Déploiement AWS avec Terraform

L'infrastructure recommandée pour ce projet est la suivante:

- 1 VPC avec un sous-réseau public uniquement pour le NAT Gateway.
- 2 sous-réseaux privés dans le même VPC pour l'EC2 applicative et le RDS PostgreSQL.
- 1 instance EC2 sans IP publique, accessible via AWS Systems Manager Session Manager.
- 1 instance RDS PostgreSQL privée, protégée par un groupe de sécurité qui n'accepte que l'EC2.

Pré-requis:

- Terraform installé localement.
- Un provider AWS configuré dans l'environnement où tu lances Terraform.
- Si tu veux que l'EC2 récupère le code automatiquement, renseigne `git_repository_url` dans les variables Terraform.

Procédure:

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform apply
```

Les valeurs `pg_dbname`, `pg_user`, `pg_password`, `pg_super_user` et `pg_super_pass` doivent correspondre à celles de `configs/.env` pour rester cohérent avec le projet. Le fichier `terraform/terraform.tfvars.example` reprend ce mapping et sert de base pour ton `terraform.tfvars` local.
Dans ce modèle, `pg_super_user` et `pg_super_pass` servent au compte maître RDS, tandis que `pg_user` et `pg_password` servent au compte applicatif utilisé par ETL, ELT et le monitoring.
Les secrets Terraform restent locaux: `terraform.tfvars` est ignoré par Git et les valeurs sensibles apparaîtront dans le state Terraform, donc il faut éviter de partager ce fichier.

Comme l'EC2 est en sous-réseau privé, l'accès se fait via SSM:

```bash
aws ssm start-session --target <ec2_instance_id>
```

Terraform renseigne ensuite `configs/.env` sur l'instance avec `PG_HOST` pointant vers le RDS, `PG_PORT=5432`, et les identifiants PostgreSQL du projet.

## CI Terraform

Un workflow GitHub Actions est disponible dans [.github/workflows/terraform.yml](.github/workflows/terraform.yml). Il exécute `terraform fmt -check`, `terraform init -backend=false` et `terraform validate` sur chaque push ou pull request qui touche le dossier `terraform/`.