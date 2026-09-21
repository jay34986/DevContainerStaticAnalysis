# Dependabot Jev Review の運用

## 初期状態と調査結果

自動承認は既定で無効です。分類・承認ロジックは `scripts/jev_review.py`、
許可ファイル・追加必須チェックは `config/jev-review.json` に分離しています。
自動マージ、PAT、追加のLLMは使用しません。

対象のDependabot設定は `develop` 向けの npm / pip / Docker / GitHub Actions です。
既存CIは主に `develop` のpushと手動実行であり、PRの依存更新テストを保証しません。
調査時のGitHubブランチAPIは `develop` を `protected: false`、必須チェックなしと返しました。
詳細な保護設定APIは連携権限不足（403）、ruleset APIは接続ツールの対象外でした。
Actionsによる承認許可設定もこの環境では確認できていません。

実行時はブランチAPIの必須チェック、適用されるrulesetの必須チェック、設定ファイルの
`required_checks` の和集合を確認します。取得失敗・チェックなしは承認不可です。
追加の `Jev Review Tests` は判定コードの単体テストであり、依存パッケージの互換性テストではありません。
既存のDockerイメージテストは今回変更していません。

## Secrets と Variables

Settings → Secrets and variables の次の両方に、同じ `JEV_API_KEY` を登録してください。

- Dependabot → New repository secret：Dependabotが起動する自動実行用。
- Actions → New repository secret：手動実行用。

キーをコード、PR、実行入力に貼り付けないでください。ワークフローは `secrets.JEV_API_KEY` を参照します。
キーがない場合は分類を中断し、承認しません。

Actions → Variables の設定（未登録なら初期値を使用）:

| 変数 | 初期値 | 用途 |
| --- | --- | --- |
| `ENABLE_AUTO_APPROVE` | `false` | 分類検証が完了するまで変更しない |
| `JEV_AUTO_APPROVE_THRESHOLD` | `0.95` | Choice応答のconfidenceの閾値 |

## Phase 1：手動で分類を比較

1. この変更を信頼できる `develop` とデフォルトブランチに取り込みます。
2. Actions → Dependabot Jev Review → Run workflow を開きます。
3. 実行ブランチはデフォルトブランチを選択します。それ以外はジョブをスキップします。
4. 既存のDependabot PR番号を入力し、`dry_run` をチェックしたまま実行します。
5. 実行詳細のSummaryで依存名・更新前後・種別・SHA・分類・confidence・各条件・除外理由を確認します。

`dry_run` はJSONの真偽値として厳密に検証します。`true` なら承認設定に関係なく承認しません。
不正値も承認不可です。Summaryの `approval_executed: false` が未承認を表します。
`HUMAN_REVIEW` は人間の確認が必要です。`SKIPPED` はDependabot以外です。
`DRY_RUN` / `AUTO_APPROVE_DISABLED` は条件を満たしても承認を実施しなかったことを表します。
API障害もSummaryの理由として表示します。ワークフローが緑でも承認可能という意味ではありません。

npm / pip の単独・グループ更新、Major、セキュリティツール、Docker、Actions更新を複数比較し、
PR番号、SHA、モデル、分類、confidence、人間の判断、相違理由を記録してください。
同じSHAでもモデルの更新により判定が変わる可能性があります。
この作業環境では実際のキーを使った分類は実施していません。

## Phase 2：自動分類

`pull_request` の `opened` / `synchronize` / `reopened` で起動します。
`develop` 向けでPR作成者が `dependabot[bot]` の場合に処理し、GitHub APIの最新情報でも再検証します。
`paths` は `.devcontainer/` 内の `package.json`、`package-lock.json`、`requirements.txt`、
`bootstrap-requirements.txt`、`Dockerfile` と `.github/workflows/**` に限定しています。
Docker / Actions更新も比較用の分類対象に含みますが、自動承認はしません。
一つでも対象パスを含むPRでは、対象外ファイルを含む全変更ファイルを承認条件の検証に使用します。
Dependabotの管理対象ファイルを追加する際は、このフィルターも更新してください。
手動・自動とも同じPython実装を使用します。`ENABLE_AUTO_APPROVE=false` を維持してください。

`Jev Review Tests` は判定スクリプト、単体テスト、JSON設定、追加した2つのワークフローが
変更されたPRまたは `develop` へのpushだけで自動実行します。
両ワークフローとも `workflow_dispatch` による手動実行はパス条件に制限されません。
パス条件でスキップされるテストを全PRの必須チェックにすると、未実行のままマージを妨げるため、
`Jev review unit tests` を全PR共通の必須チェックには指定しないでください。

Secretsを持つジョブはベースSHAをcheckoutし、PRコードを実行・インストールしません。
手動実行はデフォルトブランチのコードを使います。
PR本文、ファイル、差分はGitHub API経由のデータとしてのみ扱います。
Jevにはこれらの情報を送信するため、リポジトリ情報を外部APIで評価する運用になります。
PRコードを実行する単体テストジョブにはJevキーや書き込み権限を渡していません。

## Phase 3：条件付き承認の有効化

分類結果を人間が検証した後に、次の準備をしてください。

1. 依存更新の互換性・セキュリティを検証するPR向けCIを用意します。
2. `develop` の保護設定またはrulesetで、そのCIを必須にします。
3. 新しいコミットで古い承認を無効にする設定を有効にします。
4. Settings → Actions → General → Workflow permissions の
   `Allow GitHub Actions to create and approve pull requests` を有効にします。
5. `dry_run` で各条件が通ることを確認後、Actions Variable `ENABLE_AUTO_APPROVE` を `true` にします。

承認は `GITHUB_TOKEN` のみで実行します。組織・リポジトリ設定が書き込みを許可しなければ承認できません。
権限エラーをPATで回避しません。必要な読み取り権限は contents / checks / statuses、書き込みは pull-requests のみです。

追加必須チェックの設定例:

```json
{
  "required_checks": [
    {"context": "dependency-integration", "app_id": 15368}
  ]
}
```

これは一部の設定例です。既存設定の `required_checks` を編集してください。
実際のチェック名とGitHub App IDを確認し、適切な値を指定します。
チェックは対象のhead SHA上で成功する必要があります。merge SHA上だけの成功は採用しません。
同名の複数チェック、skipped、neutral、実行中、失敗、キャンセル、存在しないチェックは不合格です。
旧式のcommit statusも最新の状態を確認します。App ID指定時はcheck runの発行元も確認します。
必須workflow・deployment・merge queueの規則は初期実装で検証できないため承認不可です。

`Dependabot Jev Review` 自身を必須CIに含めないでください。
必須指定されている場合は循環依存として承認を止めます。
CI完了待ちや `check_suite` による再起動は行いません。CI完了後に手動実行してください。

## 判断基準と制約

- Jevが `AUTO_APPROVE` かつconfidenceが閾値以上であること。
- 同じリポジトリのDependabotによる、openかつ非DraftのPRであること。
- 許可ファイルのみを変更し、必要な情報が揃っていること。
- 必須CIがすべて対象SHAで成功していること。
- 承認直前にもPR状態、head/base SHA、対象ブランチ、CIを確認できること。

初期許可は `.devcontainer/package.json` と `.devcontainer/requirements.txt` のみです。
正確な3要素のバージョン更新をすべて列挙し、複数依存更新も個別に分類材料へ含めます。
npmのdependencies / devDependencies等の区分と、このリポジトリでの開発・静的解析用途を併記します。
バージョン範囲、プレリリース、ダウングレード、追加・削除、scripts等の変更は対象外です。
ロックファイルも現状は許可していません。対応拡張にはパーサーとテストの追加が必要です。

`dependabot/fetch-metadata` を検討しましたが、手動PR指定と自動実行を同じ経路で扱い、
PRタイトルの推測を避けるため、固定SHAのmanifest比較を採用しました。
未対応形式やDocker / Actions更新では完全なバージョン情報を保証できません。
差分・本文を分類材料として渡しますが、メタデータ不足または重要ファイルとして必ず人間に回します。
Docker、DevContainer設定、bootstrap、CI/CD設定はJevの判断にかかわらず承認対象外です。

リリースノート・脆弱性の証拠はPR本文にある情報のみで、リンク先を自動取得したり、
脆弱性なしと仮定したりしません。差分欠落、取得上限、APIエラー、タイムアウト、不正応答も承認しません。
HTTPは30秒タイムアウト、認証情報流出防止のためリダイレクト禁止、リトライなしです。
分類データは100 KB、API応答は2 MB、一覧は最大30ページで打ち切り、それ以上は承認不可です。

承認APIには評価した `commit_id` を明示します。ただしGitHub APIには「SHAが変わっていなければ承認」
という原子的な操作はないため、直前確認後の競合を完全には排除できません。
古い承認の無効化とブランチ保護を必ず併用し、マージ時の条件はGitHub側で強制してください。

Jevのconfidenceは選択肢の確率分布から算出される集中度で、安全である確率や互換性の保証ではありません。
0.95は暫定値です。依存関係の安全性を保証するシステムではありません。

## ローカルテスト

Python 3.10以降の標準ライブラリのみで実行できます。

```bash
python3 -m unittest discover -s tests -p 'test_jev_review.py' -v
```

HTTPはモック化しており、キー、ネットワーク、Dockerは不要です。
実API検証は上記の手動dry-runで行います。

## 公式仕様

- [Jev API：state / questions / answers](https://docs.typesafe.ai/api)
- [Choice応答](https://docs.typesafe.ai/primitives/choice)
- [confidenceの意味](https://docs.typesafe.ai/confidence)
- [DependabotとGitHub Actions](https://docs.github.com/en/code-security/tutorials/secure-your-dependencies/automate-dependabot-with-actions)
- [fetch-metadata](https://github.com/dependabot/fetch-metadata)
- [ブランチに適用されるruleset](https://docs.github.com/en/rest/repos/rules#get-rules-for-a-branch)
