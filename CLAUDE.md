> [AI OFFICE GOVERNANCE / BOOTSTRAP v2]
> 最初に `.governance/entry.json` の実在する central_ref を確認し、office の
> `governance/BOOTSTRAP.md` → `GLOBAL.md` → `MODES.md` を取得する。
> 共通→実行モード→本ファイル→対象README/DEVLOG/必須資料→関連repo規則の順で読む。
> `python3 tools/rules_bootstrap.py --mode <mode> --context` で本文と取得証跡を生成する。
> 別repoへ記録するときは `--related <repo>`、ツール変更は `--scope <repo>:<directory>` を追加して再実行。
> 取得失敗・モード不明は UNKNOWN、書込み・マージ等は保留。リンクだけで読了扱いにしない。
> 機密・個人情報・認証情報を記録しない。growth-logへは同repoの禁止事項と分類を読んでから。
> 朝礼はマージ禁止。通常開発の手順は朝礼の権限を広げない。現在の依頼の承認条件も守る。
> 本文の add_repo／書込可の説明は過去の環境例であり、現在の取得・書込成功を保証しない。
> 共通規則はofficeが正本。既存のgrowth-log節は互換案内であり、記録先CLAUDE.mdが正本。
> [/AI OFFICE GOVERNANCE]

# このリポジトリのルール（Claude向け）

スマホゲーム用bot（ケイトbot・矢印bot、Termux運用）のリポジトリ。**public リポジトリ**なので個人情報・認証情報は絶対にコミットしない。オーナーは綴禾（つが）。記録は Claude の担当で、頼まれなくても残す。

## growth-log（成長記録）への反映

綴禾には成長記録リポジトリ `irhn00-a11y/growth-log` がある。このセッションから見えていなくても、**add_repo で取得して書ける**。セッションの区切りで以下に当てはまったら、growth-log を取得（add_repo → clone）して追記すること：

- ツール・研究をまたいで使える教訓が出たとき → growth-log の `LEARNED.md` に要点とリンクを1行
- 新しいツール・研究を立ち上げた、v1.0 到達などの節目 → `TIMELINE.md` と `WORKS.md` に1行
- 本人が苦手・不満を口にしたとき（「だるい」「めんどい」「苦手」） → `WEAKNESSES.md` に症状として追加
- 書き方・分類のルールは growth-log 側の CLAUDE.md に従う。growth-log へは main に直接コミットでよい

**新しいリポジトリを作ったとき**は、growth-log の `repos.txt` にリポジトリ名を1行追記し、新リポジトリの CLAUDE.md にもこの節を入れる（repos.txt は本人の PC の「全部更新.bat」が読む自動 clone 一覧。忘れると本人の手元に届かない）。

