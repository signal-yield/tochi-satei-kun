# 土地価格査定クン インストール手順

仲介担当者・不動産鑑定士の方が、ご自身の PC で土地価格査定クン (tochi-satei-kun) を使い始めるための手順書です。所要時間の目安は約 30 分です。

> 💡 本書は **Windows 10/11 ユーザー向け** です。macOS 版は今後対応予定です。

---

## 0. 必要なもの

| 項目 | 要件 |
|---|---|
| OS | Windows 10 または Windows 11 |
| Claude Desktop アプリ | Cowork モード対応版（公式サイトから入手） |
| Python | 3.11 以上 |
| データ | MLIT 取引価格情報 CSV ／ 地価公示 L01 GeoJSON（§3 で取得手順を案内） |
| 通信 | 初期セットアップ時のみインターネット接続が必要 |

---

## 1. Claude Desktop アプリの準備

1. [Claude 公式サイト](https://claude.ai) から **Claude Desktop アプリ**（Windows 版）をダウンロードしてインストール
2. アプリを起動し、Anthropic アカウントでサインイン
3. 左サイドバーに「Cowork」または「Local agent」モードが表示されることを確認

---

## 2. tochi-satei-kun プラグインのインストール

Claude Desktop アプリ内のチャット欄で、以下のコマンドを順に実行します。

```
/plugin marketplace add signal-yield/tochi-satei-kun
/plugin install tochi-satei-kun
```

続いて、ターミナル (PowerShell または cmd) を開いて Python 依存パッケージをインストールします。

```
pip install pandas statsmodels scikit-learn openpyxl
```

> ⚠️ `statsmodels` のインストール時に「Microsoft Visual C++ 14.0 以上が必要」というエラーが出た場合は、[Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) を入れてから再実行してください。

---

## ⚠️ 利用上の重要な注意：スキル選択の確認

Claude Cowork でタスクを作成する際は、**必ず利用可能スキル一覧で `tochi-satei-kun` を ON にしてください**。OFFのまま実行すると、汎用LLMが「それらしい」xlsx を生成する可能性があり、本スキルの査定結果ではありません。

これは Claude Cowork のスキル選択仕様に起因する制約で、本スキルの設計者は透明性をもって本注意を開示しています。

### 本スキルの出力かどうかを確認する4条件

いずれか欠けていたら、スキルONを確認の上、再実行してください：

1. **ファイルサイズ 40KB以上**（10〜20KBは捏造の疑い）
2. **シート 2枚構成**（確認用 / グラフ）
3. 確認用シート A1セルに **`tochi-satei-kun v{バージョン} 出力`** の表示
   （どのツールのどのバージョンで作成された出力かを確認するための表示であり、
   電子署名や真正性検証の仕組みではありません）
4. 確認用シートに **「■ ヘドニック回帰サマリ」** セクション

---

## 3. データファイルの取得

土地価格査定クンは **国土交通省の公的データ** を使ってヘドニック回帰を都度実施します。以下 2 種類のファイルを事前に手元へ用意してください。

### 3-1. MLIT 取引価格情報 CSV

- 取得先: [国土交通省 不動産情報ライブラリ](https://www.reinfolib.mlit.go.jp/)
- 「取引価格情報」→ 対象都道府県・市区町村・直近 3〜5 年を選択して CSV ダウンロード
- 推奨保存先: `C:\Users\<あなた>\Documents\tochi-satei-kun-data\mlit\`

### 3-2. 地価公示 L01 GeoJSON

- 取得先: [国土数値情報ダウンロードサイト](https://nlftp.mlit.go.jp/ksj/) の「地価公示 (L01)」
- 対象年度（例: 令和 7 年度）の GeoJSON 形式をダウンロード
- 推奨保存先: `C:\Users\<あなた>\Documents\tochi-satei-kun-data\koji\`

> ℹ️ 基準地価 (L02) は対象外です。必ず **地価公示 (L01)** をご使用ください。

---

## 4. Watcher のセットアップ（重要）

### なぜ必要か

Cowork のサンドボックスはセキュリティ上の理由で、Claude が直接ホスト PC のデスクトップへファイルを書き込めません。生成した査定書 (xlsx) を手元に届けるため、**Watcher** という小さな常駐スクリプトを Windows 側で動かして、Cowork の outputs フォルダを監視・自動コピーします。一度セットアップすればバックグラウンドで動き続けます。

### 手順

**4-1.** GitHub からダウンロードしたリポジトリの `tools/watch_cowork_outputs.py` を、ユーザーフォルダ直下にコピーします。

- コピー先: `C:\Users\<あなた>\watch_cowork_outputs.py`

**4-2.** `Win + R` キーを押し、表示された「ファイル名を指定して実行」に以下を入力して Enter:

```
shell:startup
```

→ Windows のスタートアップフォルダが開きます。

**4-3.** リポジトリの `tools/watch_cowork_outputs.bat` を、開いたスタートアップフォルダにコピーします。

**4-4.** コピーした `.bat` ファイルをダブルクリックして初回起動します（または PC を再起動）。バックグラウンドで `pythonw.exe` が動き始めます。

### 動作確認

メモ帳などで `C:\Users\<あなた>\watch_cowork_outputs.log` を開きます。以下の 3 行が記録されていれば成功です。

```
[YYYY-MM-DD HH:MM:SS] Watcher 起動
[YYYY-MM-DD HH:MM:SS] 監視先: C:\Users\<あなた>\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\...
[YYYY-MM-DD HH:MM:SS] 配置先: C:\Users\<あなた>\OneDrive\デスクトップ  (環境により表記異なる)
```

「WATCH_ROOT がまだ存在しません」と出ている場合は、Claude Desktop アプリを一度起動して Cowork タスクを 1 つ作ると、監視対象フォルダが生成されます。

---

## 5. 初回タスク実行

1. Claude Desktop アプリで **新しい Cowork タスク** を作成します。
2. 🚨 **【最重要】** タスクの「利用可能スキル」設定で、`tochi-satei-kun` を **ON** にし、汎用スキル（`anthropic-skills:xlsx` 等）は **OFF** にしてください。これを怠ると、Claude が汎用 xlsx スキルにフォールバックして、係数の入っていない「それっぽいが捏造の」査定書が生成される失敗モードに陥ります。
3. §3 で取得した **MLIT CSV** と **L01 GeoJSON** を、タスクのチャット欄にドラッグ&ドロップで投入します。
4. 物件情報をプロンプトで指示します。例:

   ```
   以下の物件を査定してください。
   住所: 東京都世田谷区赤堤 X-Y-Z
   面積: 120 sqm
   用途地域: 第一種低層住居専用地域
   形状: 整形地
   接道: 南側 6m 公道
   ```

5. パイプラインが走り終わると、Cowork outputs フォルダ内に `土地査定_<物件略号>_<YYYYMMDD>.xlsx` が出力されます。
6. **5〜10 秒以内** にデスクトップへ同名ファイルがコピーされていることを確認してください。これが Watcher の働きです。

---

## 6. トラブルシューティング

### 出力がデスクトップに出てこない

- `C:\Users\<あなた>\watch_cowork_outputs.log` を確認
- "Watcher 起動" の行があり、それ以降エラーが出ていなければ Watcher は稼働中
- Cowork outputs フォルダに該当 xlsx が出ているかを確認（出ていなければそもそも Cowork 側のタスクが完了していない）

### 査定書の中身が捏造っぽい（係数欄が空、出典 5 件が架空、シートが 6 枚ある）

- これは Claude が `tochi-satei-kun` ではなく汎用 xlsx スキルにフォールバックしたサインです
- §5 手順 2 に戻り、タスクの「利用可能スキル」で `tochi-satei-kun` のみが ON になっているか確認
- 同じ症状が出る場合は、新しいタスクを作り直し、最初からスキル選択を見直してください

### "WATCH_ROOT not found" や "WATCH_ROOT がまだ存在しません" が出続ける

- Claude Desktop アプリを一度起動し、Cowork タスクを 1 件作成すると `local-agent-mode-sessions` フォルダが生成されます

### `pip install statsmodels` が失敗する

- Visual C++ Build Tools が未インストールの可能性
- [Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) をインストール後、再度 `pip install statsmodels` を実行

### Watcher を止めたい

- タスクマネージャを開き、「プロセス」タブで `pythonw.exe` を選択 → 「タスクの終了」
- 再開する場合はスタートアップフォルダの `.bat` をダブルクリック

---

## 付録: なぜ Watcher が必要か（仕組みの解説）

Claude Desktop アプリの Cowork モードは、セキュリティ上の理由で **サンドボックス** という隔離環境で動作します。サンドボックスはホスト PC のファイルシステムに直接書き込めず、書き込めるのは Cowork 専用の outputs フォルダだけです。

土地価格査定クン v1.2.7／v1.2.8 ではプラグイン内部で `shutil.copy` を使ってデスクトップへの自動コピーを試みましたが、すべてサンドボックス境界で阻まれました。これは **構造的な壁** であり、プラグイン内部からは越えられません。

そこで Watcher パターン — Cowork の **外側** に小さな監視スクリプトを置き、サンドボックス越しに outputs フォルダを覗いて、新しい xlsx が出たらユーザーのデスクトップへコピーする — を採用しました。コピーはホスト OS 上で行われるので、サンドボックスの制約を受けません。

この設計は土地価格査定クンが掲げる **「白箱方式 (white-box AVM)」** の理念とも一致します。査定の根拠（係数、p 値、標準誤差、比較事例 5 件）をユーザーへ全開示するだけでなく、出力ファイルそのものもユーザーが完全に手元で所有・検証できる形にしました。

---

## 関連リンク

- [README.md](./README.md) — プロジェクト概要、AVM 設計思想
- [LICENSE](./LICENSE) — Apache License 2.0
- [GitHub Repository](https://github.com/signal-yield/tochi-satei-kun)

ご質問・不具合報告は GitHub Issues までお願いします。
