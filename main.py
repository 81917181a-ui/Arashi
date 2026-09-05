import os
import asyncio
import random
import threading
import time
import requests
import discord
from discord import app_commands
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
import uvicorn

# 環境変数の読み込み
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# 設定情報
NOTIFICATION_CHANNEL_ID = 1545620371477106868
RESTRICTED_GUILD_ID = 1510021467155202048

# 【重要】RenderのWebサービスのURLをここに設定してください（例: "https://xxx.onrender.com"）
# まだ決まっていない場合は空文字 "" のままでOKです。デプロイ後にURLを入れて再プッシュしてください。
RENDER_EXTERNAL_URL = "https://arashi-3vci.onrender.com" 

# FastAPIアプリの初期化
app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "Bot is running!"}

@app.get("/link")
def link_account(code: str = None):
    """
    OAuth2認証のコールバック用エンドポイント（将来の拡張用）
    """
    return {"message": "Link endpoint ready."}

# Discord Botの定義
class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True  # メンバーリスト取得に必須
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print("スラッシュコマンドを同期しました。")

client = MyBot()

@client.event
async def on_ready():
    print(f'ログインしました: {client.user}')

# 1. /random-mention コマンド
@client.tree.command(name="random-mention", description="サーバー内のメンバーを指定人数分ランダムにメンションします")
@app_commands.describe(count="メンションする人数")
async def random_mention(interaction: discord.Interaction, count: int):
    # 制限サーバーのチェック
    if interaction.guild and interaction.guild.id == RESTRICTED_GUILD_ID:
        await interaction.response.send_message("このサーバーでは `/random-mention` コマンドは使用できません。", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    
    # ボット自身を除外したメンバーリスト
    members = [m for m in interaction.guild.members if not m.bot]
    
    if count > len(members):
        await interaction.followup.send(f"指定された人数 ({count}人) が現在の有効なメンバー数を超えています。")
        return

    chosen_members = random.sample(members, count)
    await interaction.followup.send(f"【ランダムメンション開始】{count}人を10秒間隔でメンションします。")
    
    for member in chosen_members:
        await interaction.channel.send(f"{member.mention} さん、こんにちは！")
        await asyncio.sleep(10)  # 10秒のギャップ

# 2. /mention コマンド
@client.tree.command(name="mention", description="こんにちは！ @everyone を指定回数送信します")
@app_commands.describe(times="送信する回数")
async def mention_everyone(interaction: discord.Interaction, times: int):
    # 制限サーバーのチェック
    if interaction.guild and interaction.guild.id == RESTRICTED_GUILD_ID:
        await interaction.response.send_message("このサーバーでは `/mention` コマンドは使用できません。", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    
    await interaction.followup.send(f"【@everyone 連投開始】全 {times} 回、10秒間隔で送信します。")
    
    for _ in range(times):
        await interaction.channel.send("こんにちは！ @everyone")
        await asyncio.sleep(10)  # 10秒のギャップ

# 3. /mention-role コマンド
@client.tree.command(name="mention-role", description="入力されたテキストに一番似ているロールを自動で特定してメンションします")
@app_commands.describe(role_name="検索したいロールのキーワード")
async def mention_role(interaction: discord.Interaction, role_name: str):
    await interaction.response.defer(thinking=True)
    
    guild = interaction.guild
    if not guild.roles:
        await interaction.followup.send("サーバーにロールが存在しません。")
        return

    # 一番文字が似ている（部分一致・前方一致など）ロールを簡易スコアリングで探索
    best_role = None
    max_score = -1

    for role in guild.roles:
        if role.is_default():  # @everyoneロールは除外
            continue
        
        r_name = role.name.lower()
        target = role_name.lower()
        
        # スコアリングロジック（完全一致 > 前方一致 > 部分一致）
        score = 0
        if target == r_name:
            score = 100
        elif target in r_name:
            score = 50
        elif r_name in target:
            score = 30
        
        if score > max_score:
            max_score = score
            best_role = role

    if not best_role or max_score <= 0:
        await interaction.followup.send(f"「{role_name}」に似ているロールが見つかりませんでした。")
        return

    await interaction.followup.send(f"一番似ているロールとして **{best_role.name}** をメンションします！")
    await interaction.channel.send(f"{best_role.mention} こんにちは！")

# 4. /link コマンド（外部連携・情報通知用）
@client.tree.command(name="link", description="アカウントを連携し、メールアドレスなどの情報を通知します")
async def link_account_cmd(interaction: discord.Interaction):
    # ユーザーアプリとしてどこからでも呼び出せる想定のリンク案内
    # 実際のOAuth2認証URL（各自のサービスURLやDiscord認証URL）に書き換え可能
    auth_url = f"{RENDER_EXTERNAL_URL}/link" if RENDER_EXTERNAL_URL else "https://discord.com/oauth2/authorize..."
    
    # チャンネルID: 1545620371477106868 へのテスト通知のシミュレーション、または案内
    channel = client.get_channel(NOTIFICATION_CHANNEL_ID)
    if channel:
        try:
            await channel.send(f"🔗 ユーザー `{interaction.user}` が `/link` コマンドを実行しました。")
        except Exception as e:
            print(f"通知送信エラー: {e}")

    await interaction.response.send_message(
        f"アカウント連携用リンクはこちらです:\n{auth_url}\n(※Discordの仕様上、パスワードは取得できません)", 
        ephemeral=True
    )
# 5. /kick-role コマンド（入力されたテキストに一番似ているロールのメンバーをキック）
@client.tree.command(name="kick-role", description="入力されたロール名に一番似ているロールのメンバーをキックします")
@app_commands.describe(role_name="キックしたい対象のロール名（キーワード）")
async def kick_role(interaction: discord.Interaction, role_name: str):
    # 実行者がキック権限を持っているかチェック
    if not interaction.user.guild_permissions.kick_members:
        await interaction.response.send_message("あなたにはこのコマンドを実行する権限（メンバーをキック）がありません。", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    
    guild = interaction.guild
    if not guild.roles:
        await interaction.followup.send("サーバーにロールが存在しません。")
        return

    # 一番似ているロールを探索（mention-roleと同じ判定ロジック）
    best_role = None
    max_score = -1

    for role in guild.roles:
        if role.is_default():  # @everyoneロールは除外
            continue
        
        r_name = role.name.lower()
        target = role_name.lower()
        
        score = 0
        if target == r_name:
            score = 100
        elif target in r_name:
            score = 50
        elif r_name in target:
            score = 30
        
        if score > max_score:
            max_score = score
            best_role = role

    if not best_role or max_score <= 0:
        await interaction.followup.send(f"「{role_name}」に似ているロールが見つかりませんでした。")
        return

    # そのロールを持っているメンバーを取得（ボット自身や自分自身、権限持ちは除外するなどの安全対策を挟むとより良いです）
    members_to_kick = [m for m in best_role.members if not m.bot and m != guild.owner]

    if not members_to_kick:
        await interaction.followup.send(f"ロール **{best_role.name}** を持っている対象メンバーがいません（または除外対象のみです）。")
        return

    await interaction.followup.send(f"ロール **{best_role.name}** が一致しました。対象メンバーのキック処理を開始します（対象: {len(members_to_kick)}人）...")

    success_count = 0
    fail_count = 0

    for member in members_to_kick:
        try:
            await member.kick(reason=f"ロール '{best_role.name}' 一致による自動キック (実行者: {interaction.user})")
            success_count += 1
            await asyncio.sleep(2)  # Discord APIに負荷をかけないよう少しウェイトを挟む
        except Exception as e:
            print(f"キック失敗 ({member}): {e}")
            fail_count += 1

    await interaction.channel.send(f"⚠️ キック処理が完了しました。\n成功: {success_count}人 / 失敗（権限不足など）: {fail_count}人")
    
# スリープ防止用：10分ごとに自分自身へアクセスするバックグラウンドタスク
def self_ping_loop():
    while True:
        time.sleep(600)  # 10分 (600秒)
        if RENDER_EXTERNAL_URL:
            try:
                response = requests.get(RENDER_EXTERNAL_URL)
                print(f"[Self-Ping] 成功: Status {response.status_code}")
            except Exception as e:
                print(f"[Self-Ping] 失敗: {e}")

# バックグラウンドスレッドの起動
threading.Thread(target=self_ping_loop, daemon=True).start()

# メイン実行処理（FastAPIとDiscord Botを同時に走らせる）
if __name__ == "__main__":
    # 別スレッドでDiscord Botを走らせる
    threading.Thread(target=lambda: client.run(TOKEN), daemon=True).start()
    
    # メインスレッドでFastAPI (Uvicorn) サーバーを起動 (Render指定のPORTに対応)
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
