# Discord Bot (Python / discord.py)

## 機能
- `/hello` … 「こんにちは！」と返信
- `/createchannel (個数)` … 指定した個数のテキストチャンネルを作成
- `/bye [roleID]` … 指定したロールIDを持つメンバーを全員キック
- オフライン防止 … Render Web Serviceがスリープしないよう、10分ごとに `https://arashi-3vci.onrender.com` にアクセス
- Flaskで簡易Webアプリとしても動作（`/` にアクセスすると生存確認メッセージを返す）

## 事前準備

### 1. Discord Developer Portalでの設定
1. https://discord.com/developers/applications でアプリケーションを作成
2. 「Bot」タブでBotを作成し、トークンを取得（あとで`DISCORD_TOKEN`として使用）
3. 「Bot」タブの「Privileged Gateway Intents」で **SERVER MEMBERS INTENT** をONにする（`/bye`でロール保持者を取得するため必須）
4. 「OAuth2 > URL Generator」で `bot` と `applications.commands` にチェックを入れ、必要な権限（Manage Channels, Kick Members など）を選んで生成されたURLからサーバーに招待する

### 2. ローカルでの実行
```bash
pip install -r requirements.txt
export DISCORD_TOKEN="あなたのBotトークン"
python main.py
```

### 3. Render Web Serviceへのデプロイ
1. このフォルダ（main.py, requirements.txt）をGitHubリポジトリにpush
2. Renderで「New +」→「Web Service」を選択し、リポジトリを接続
3. 設定:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
4. 「Environment」タブで環境変数を追加:
   - `DISCORD_TOKEN` = あなたのBotトークン
   - `KEEP_ALIVE_URL` = `https://arashi-3vci.onrender.com`（変更しない場合は未設定でもOK。コード内にデフォルト値あり）
5. デプロイ後、発行されたURLがそのままオフライン防止のpingを受ける対象にもなります（コード内の`KEEP_ALIVE_URL`と実際のURLが同じであれば、自分自身を10分ごとに起こす形になります）

## 注意点
- Renderの無料プランは一定時間アクセスがないとスリープしますが、このBotが10分ごとに自分のURLへアクセスすることでスリープを防ぎます。
- `/createchannel` と `/bye` はそれぞれ「チャンネル管理権限」「メンバーキック権限」を持つユーザーのみ実行できます。
- スラッシュコマンドがサーバーに反映されるまで数分かかる場合があります。
