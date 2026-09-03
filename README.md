# awslens

AWS 環境のリソースをスナップショットし、Markdown / YAML で出力する CLI ツール。
2 時点のスナップショットを比較する diff ツール付き。

## Requirements

- Python 3.13+
- AWS credentials (profile or environment variables)

## Setup

```bash
uv sync
```

## Single-file build

`core/` と `fetchers/` の自作実装だけを 1 つの Python ファイルに展開できます。
`boto3` と `PyYAML` は意図的に同梱しないため、実行環境に別途インストールしてください。

```bash
uv run python scripts/build_single_file.py
# dist/awslens.py と dist/awslens-diff.py を生成

pip install boto3 pyyaml
python dist/awslens.py --profile myproj --region ap-northeast-1
python dist/awslens-diff.py before.yaml after.yaml
```

生成されたファイルはローカルモジュールを内包しているため、`core/` と `fetchers/` をコピーする必要はありません。
出力先は `--output-dir` で変更できます。

## awslens

AWS リソースの収集・出力を行うメインコマンド。

### Usage

```bash
# 全サービスを取得（Markdown 形式）
uv run awslens --profile myproj --region ap-northeast-1

# YAML 形式で出力
uv run awslens --profile myproj --format yaml

# サービスを指定して取得
uv run awslens --profile myproj --services lambda,s3,dynamodb

# ファイルに出力
uv run awslens --profile myproj --output resources.yaml --format yaml

# CloudFormation stack でフィルタリング
uv run awslens --profile myproj --stack my-app-stack

# 複数 stack・ワイルドカード指定
uv run awslens --profile myproj --stack "my-app-*" --stack shared-infra
```

### Options

| Option | Description |
|---|---|
| `--profile PROFILE` | AWS CLI profile name |
| `--region REGION` | AWS region |
| `--output FILE` | Output file path (default: stdout) |
| `--services LIST` | Comma-separated services (default: all) |
| `--stack STACK` | CloudFormation stack name (repeatable, wildcards supported) |
| `--format FORMAT` | `markdown` (default) or `yaml` |

### Supported Services

| Category | Services |
|---|---|
| CDN / Storage | cloudfront, s3 |
| Compute | lambda, ecs (clusters, services, task definitions), ecr, apprunner |
| Networking | vpc, securitygroup, alb |
| Database | rds, dynamodb |
| Messaging | sns, sqs, eventbridge (rules, Scheduler schedules) |
| API | apigateway (REST + HTTP) |
| DNS / Certs | route53, acm |
| Monitoring | cloudwatch, stepfunctions, secrets |
| Management | iam_dependencies, cfn_stacks |

### Output Formats

**Markdown** (`--format markdown`, default)

````markdown
# AWS Resources - myproj (ap-northeast-1)
Generated: 2026-03-02T12:00:00+0900

## Lambda

```yaml
functions:
  - name: my-function
    runtime: python3.13
    memory: 256
```
````

**YAML** (`--format yaml`)

```yaml
metadata:
  profile: myproj
  region: ap-northeast-1
  generated: "2026-03-02T12:00:00+0900"
lambda:
  functions:
    - name: my-function
      runtime: python3.13
      memory: 256
s3:
  buckets:
    - name: my-bucket
```

## awslens-diff

2 つの YAML スナップショットを比較し、リソースの追加・削除・変更を検出する。

### Usage

```bash
# テキスト形式で差分表示
uv run awslens-diff before.yaml after.yaml

# YAML 形式で差分出力
uv run awslens-diff before.yaml after.yaml --format yaml

# ファイルに保存
uv run awslens-diff before.yaml after.yaml --output diff.txt
```

### Options

| Option | Description |
|---|---|
| `old` | 比較元の YAML ファイルパス |
| `new` | 比較先の YAML ファイルパス |
| `--format FORMAT` | `text` (default) or `yaml` |
| `--output FILE` | Output file path (default: stdout) |

### Output Example

```
--- before.yaml  (2026-03-01T10:00:00+0900)
+++ after.yaml   (2026-03-02T10:00:00+0900)

[~] lambda
  + notification-sender
  - batch-processor
  ~ api-handler
    memory: 256 -> 512
[~] ecs
  ~ main-cluster
    running_tasks: 4 -> 6
    services[0].desired: 2 -> 3
[+] app_runner (new section)
  + my-app-runner-svc
```

| Symbol | Meaning |
|---|---|
| `[+]` | セクション追加 |
| `[-]` | セクション削除 |
| `[~]` | セクション内に変更あり |
| `+` | リソース追加 |
| `-` | リソース削除 |
| `~` | リソース変更（詳細がインデントで続く） |
