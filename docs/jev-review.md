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
| `JEV_MIN_CONFIDENCE` | `0.40` | Jev自身の判断の確からしさの下限 |
| `JEV_MIN_AUTO_PROBABILITY` | `0.60` | AUTOへの相対的支持度の下限 |
| `JEV_MIN_AUTO_MARGIN` | `0.20` | AUTOとHUMANの確率差の下限 |

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
Docker / Actions更新は決定論的precheckでHUMANに確定し、Jev APIを呼びません。
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

- Jevが `AUTO_APPROVE` かつconfidence、AUTO probability、AUTO−HUMAN marginがそれぞれ閾値以上であること。
- AUTOとHUMANの同率は、margin閾値を0に設定しても人間確認に回すこと。
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
メタデータ不足または重要ファイルの場合はJevへの送信前に人間確認へ確定します。
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

## PoC後のゲートと再評価

旧変数 `JEV_AUTO_APPROVE_THRESHOLD` は使用しません。上記3変数へ移行してください。
値は0〜1の有限数のみ許可し、不正な設定では承認を停止します。
confidenceは選択肢probabilityの最大値とは別に扱います。
Summaryは `confidence`、全 `probabilities`、`auto_margin`、使用した `jev_thresholds`、
4条件の `jev_gates`（PASS/FAIL）、`auto_candidate` と最終 `result` を出力します。
API未呼び出し時は `decision: NOT_CALLED`、未取得の数値はnull、ゲートはNOT_EVALUATEDです。
precheckで除外した場合は `jev_skip_reason: Deterministic human-review condition matched` と具体的理由を表示します。
API失敗／不正応答時は `decision: ERROR` とし、必ず人間確認へ回します。

`auto_candidate: true` はJevの4条件を満たしたことだけを示します。
CI未設定やSHA変更などがあれば、候補でも最終結果は `HUMAN_REVIEW` です。
全ガード通過時のみ、手動dry-runでは `DRY_RUN`、承認無効時は `AUTO_APPROVE_DISABLED` になります。
実行一覧には `Dependabot Jev Review PR #166` のようにPR番号が表示されます。
チェック名は循環検知のため `Dependabot Jev Review` のままです。

2026-09-21に実PRのhead/base manifestと変更ファイルを取得し、提示されたPoCスコアを再生しました。
次の結果は新しいJev API応答ではありません。この作業環境にJEV_API_KEY／GITHUB_TOKENはなく、
変更後のワークフローをGitHub上で再実行する検証は未実施です。
取り込み後、上記Phase 1の手順で6 PRを `dry_run=true`、`ENABLE_AUTO_APPROVE=false` のまま再評価してください。

| PR | head SHA（先頭） | confidence | AUTO | HUMAN | margin | AUTO候補 |
| --- | --- | --- | --- | --- | --- | --- |
| #166 | 339144fa8654 | 0.51 | 0.67 | 0.31 | 0.36 | Yes |
| #170 | b74d4de37f54 | 0.22 | 0.48 | 0.48 | 0.00 | No |
| #184 | bee34910baaa | 0.25 | 0.48 | 0.50 | -0.02 | No |
| #185 | d0a3e9dc344f | 0.94 | 0.03 | 0.96 | -0.93 | No |
| #189 | d82a33fefc9c | 0.47 | 0.65 | 0.31 | 0.34 | Yes |
| #190 | 1fd8215364ed | 0.47 | 0.65 | 0.31 | 0.34 | Yes |

必須CIなしを再現した場合は6件とも最終結果がHUMANです。成功CIを与えた単体テストでは候補3件がDRY_RUNになります。
PR #170と#184は人間の許容範囲でも、モデルの曖昧さを優先してHUMANへ倒します。

## Required CI調査（設定変更なし）

2026-09-21時点のローカルworkflowと、対象6 PRのhead SHAのcheck-runs／statusesを確認しました。
全6件で `CodeQL` のcompleted/successが存在し、legacy statusは0件でした。
例: [#166のhead checks](https://api.github.com/repos/jay34986/DevContainerStaticAnalysis/commits/339144fa8654bded90045bf21dab8f2b6010ca2b/check-runs)。
CodeQLの発行元App IDは `57789` です。リポジトリ内にはCodeQL workflowがないため、
設定起源と将来の全依存更新での実行保証までは確認できていません。

| workflow／チェック | 現在の自動起動条件 | Dependabot依存manifest PRの必須候補 |
| --- | --- | --- |
| CodeQL | 対象6件のhead上で実行・成功を確認 | 候補。起動設定の確認が必要 |
| Build and Scan Docker Image with SBOM / build-and-scan | develop push、依存manifest／Dockerfile変更 | PRでは起動しない。PR対応後の本命候補 |
| Lint and Validate Dockerfile / Hadolint | develop push、Dockerfile変更 | 現状対象外 |
| Lint and Validate GitHub Actions Workflows / Actionlint, Ghalint | develop push、workflow変更 | 現状対象外 |
| Lint and Validate Markdown Files / MarkdownLint | develop push、Markdown変更 | 現状対象外 |
| Lint and Validate Shell Scripts / Shellcheck | develop push、pre-commit変更 | 現状対象外 |
| Yamllint / Yamllint | develop push、対象YAML変更 | 現状対象外 |
| Jev Review Tests / Jev review unit tests | 判定コード・設定・関連workflowのPR／develop push | 依存manifestだけでは起動せず、全依存PRには指定不可 |
| Dependabot Jev Review | develop向け対象パスのPR | 自分自身なので必須指定禁止 |

全ローカルworkflowに手動起動もありますが、手動でベースブランチ上に作った成功はPRのhead CIの代わりになりません。
現時点で検討できる設定候補は以下です。`config/jev-review.json` の `required_checks: []` は変更していません。

```json
{"context": "CodeQL", "app_id": 57789}
```

CodeQLは対象6件でJev承認なしに既に成功しており、観測した実行に循環依存はありません。
ローカルCIにもJev完了を待つ `needs`／`workflow_run` はありません。
将来PR対応するbuild-and-scanもJevの結果を待たず独立起動させ、Jevだけがその成功を読む構成としてください。
CodeQL単独ではnpm等のインストール・実行互換性を検証できないため、自動承認の有効化前には
Dockerビルド＋TestinfraのPR対応を推奨します。Dependabotの読み取り権限で実行できること、
対象head SHAに成功チェックが付くこと、変更パスによる未起動がないことを確認した後に必須化してください。
今回、起動条件・保護設定・Required CI・承認フラグのリモート設定は変更していません。
