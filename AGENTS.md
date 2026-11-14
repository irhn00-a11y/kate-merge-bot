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

# Agent entry

このリポジトリ固有の指示は `CLAUDE.md` を必ず読む。AGENTS.mdだけで完了にしない。
Python/ghを使えない環境では、連携ツールでentry.jsonのrefと必須文書を取得して同じ証跡を残す。
