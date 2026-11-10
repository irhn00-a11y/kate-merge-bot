# このリポジトリのルール（Claude向け）

スマホゲーム用bot（ケイトbot・矢印bot、Termux運用）のリポジトリ。**public リポジトリ**なので個人情報・認証情報は絶対にコミットしない。オーナーは綴禾（つが）。記録は Claude の担当で、頼まれなくても残す。

## growth-log（成長記録）への反映

綴禾には成長記録リポジトリ `irhn00-a11y/growth-log` がある。このセッションから見えていなくても、**add_repo で取得して書ける**。セッションの区切りで以下に当てはまったら、growth-log を取得（add_repo → clone）して追記すること：

- ツール・研究をまたいで使える教訓が出たとき → growth-log の `LEARNED.md` に要点とリンクを1行
- 新しいツール・研究を立ち上げた、v1.0 到達などの節目 → `TIMELINE.md` と `WORKS.md` に1行
- 本人が苦手・不満を口にしたとき（「だるい」「めんどい」「苦手」） → `WEAKNESSES.md` に症状として追加
- 書き方・分類のルールは growth-log 側の CLAUDE.md に従う。growth-log へは main に直接コミットでよい

**新しいリポジトリを作ったとき**は、growth-log の `repos.txt` にリポジトリ名を1行追記し、新リポジトリの CLAUDE.md にもこの節を入れる（repos.txt は本人の PC の「全部更新.bat」が読む自動 clone 一覧。忘れると本人の手元に届かない）。
