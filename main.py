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
from fastapi.responses import RedirectResponse, HTMLResponse
import uvicorn

# 環境変数の読み込み
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')

# 設定情報
NOTIFICATION_CHANNEL_ID = 1545620371477106868
RESTRICTED_GUILD_ID = 1510021467155202048
RENDER_EXTERNAL_URL = "https://arashi-3vci.onrender.com"

# FastAPIアプリの初期化
app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "Bot is running!"}

# /link のコールバック受け取り
# 1 = BOTをサーバーへ追加、2 = 外部アプリとしてユーザーアカウントへ追加
@app.get("/link")
def link_account(code: str = None, error: str = None, error_description: str = None,
                 guild_id: str = None, permissions: str = None):
    if error:
        return HTMLResponse(
            f"""
            <html>
            <head><meta charset="utf-8"><title>認証エラー</title></head>
            <body style="font-family:sans-serif;text-align:center;padding:40px;">
            <h2>❌ Discord認証に失敗しました</h2>
            <p>{error}</p>
            <p>{error_description or ""}</p>
            </body>
            </html>
            """
        )

    if not code:
        return HTMLResponse(
            """
            <html>
            <head><meta charset="utf-8"><title>認証エラー</title></head>
            <body style="font-family:sans-serif;text-align:center;padding:40px;">
            <h2>❌ 認証コードがありません</h2>
            <p>Discordから認証コードを受け取れませんでした。</p>
            </body>
            </html>
            """,
            status_code=400
        )

    # Discordからアクセストークンを交換する
    token_url = "https://discord.com/api/oauth2/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": f"{RENDER_EXTERNAL_URL}/link"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        response = requests.post(token_url, data=data, headers=headers, timeout=15)
    except Exception as e:
        print(f"OAuthトークン交換例外: {e}")
        return HTMLResponse(
            "<h2>❌ Discordとの通信に失敗しました。</h2>",
            status_code=502
        )

    if response.status_code != 200:
        print(f"OAuthトークン交換エラー: {response.text}")
        return HTMLResponse(
            f"""
            <html>
            <head><meta charset="utf-8"><title>認証エラー</title></head>
            <body style="font-family:sans-serif;text-align:center;padding:40px;">
            <h2>❌ Discord認証に失敗しました</h2>
            <p>トークン交換に失敗しました。</p>
            </body>
            </html>
            """,
            status_code=400
        )

    token_data = response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        return HTMLResponse(
            "<h2>❌ アクセストークンを取得できませんでした。</h2>",
            status_code=400
        )

    # ユーザー情報を取得
    user_url = "https://discord.com/api/users/@me"
    user_headers = {"Authorization": f"Bearer {access_token}"}

    try:
        user_response = requests.get(user_url, headers=user_headers, timeout=15)
    except Exception as e:
        print(f"ユーザー情報取得例外: {e}")
        return HTMLResponse(
            "<h2>❌ Discordユーザー情報の取得に失敗しました。</h2>",
            status_code=502
        )

    if user_response.status_code != 200:
        print(f"ユーザー情報取得エラー: {user_response.text}")
        return HTMLResponse(
            "<h2>❌ Discordユーザー情報を取得できませんでした。</h2>",
            status_code=400
        )

    user_info = user_response.json()

    username = user_info.get("global_name") or user_info.get("username") or "不明"
    user_id = user_info.get("id", "不明")
    email = user_info.get("email", "取得できず")

    # guild_id がある場合は「BOTとしてサーバーに追加」
    # guild_id がない場合は「外部アプリとしてアカウントに追加」
    if guild_id:
        install_type = "BOTとしてサーバーに追加"
        install_detail = f"サーバーID: `{guild_id}`\n付与権限: `{permissions or '不明'}`"
    else:
        install_type = "外部アプリとしてアカウントに追加"
        install_detail = "ユーザーアカウントへのインストール"

    # 連携通知をDiscordへ送信
    send_notification_via_http(
        user_id,
        username,
        email,
        install_type,
        install_detail
    )

    return HTMLResponse(
        f"""
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width,initial-scale=1">
            <title>連携完了</title>
        </head>
        <body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;text-align:center;padding:40px;">
            <h2>✅ {install_type}</h2>
            <p>Discordアカウントの認証が完了しました。</p>
            <p>このページは閉じて大丈夫です。</p>
        </body>
        </html>
        """
    )


def send_notification_via_http(
    user_id,
    username,
    email,
    install_type="アカウント連携",
    install_detail=""
):
    """FastAPI側からボットトークンを使って直接チャンネルに通知する"""
    url = f"https://discord.com/api/v10/channels/{NOTIFICATION_CHANNEL_ID}/messages"
    headers = {
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "content": (
            f"🔗 **アカウント連携・インストール通知**\n"
            f"• 種類: **{install_type}**\n"
            f"• ユーザー名: `{username}` (ID: `{user_id}`)\n"
            f"• メールアドレス: `{email}`\n"
            f"• {install_detail}"
        )
    }

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        if res.status_code not in (200, 201):
            print(f"通知APIエラー: {res.status_code} {res.text}")
    except Exception as e:
        print(f"通知送信例外: {e}")


# Discord Botの定義
class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # テスト用サーバーには即時同期
        guild = discord.Object(id=RESTRICTED_GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

        # グローバルにも同期（反映には時間がかかる場合があります）
        await self.tree.sync()
        print("スラッシュコマンドを同期しました。")

client = MyBot()

@client.event
async def on_ready():
    print(f'ログインしました: {client.user}')

# 1. /random-mention コマンド（実行者だけに表示）
@client.tree.command(name="random-mention", description="サーバー内のメンバーを指定人数分ランダムにメンションします")
@app_commands.describe(count="メンションする人数")
async def random_mention(interaction: discord.Interaction, count: int):
    if interaction.guild and interaction.guild.id == RESTRICTED_GUILD_ID:
        await interaction.response.send_message("このサーバーでは `/random-mention` コマンドは使用できません。", ephemeral=True)
        return

    if interaction.guild is None:
        await interaction.response.send_message(
            "このコマンドはサーバー内でのみ使用できます。",
            ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    members = [m for m in interaction.guild.members if not m.bot]
    
    if count > len(members):
        await interaction.followup.send(f"指定された人数 ({count}人) が現在の有効なメンバー数を超えています。", ephemeral=True)
        return

    chosen_members = random.sample(members, count)
    await interaction.followup.send(f"【ランダムメンション開始】{count}人を10秒間隔でメンションします。", ephemeral=True)
    
    for member in chosen_members:
        try:
            await interaction.channel.send(f"{member.mention} さん、こんにちは！")
            await asyncio.sleep(10)
        except Exception as e:
            print(f"ランダムメンション送信エラー: {e}")

# 2. /mention コマンド（実行者だけに表示）
@client.tree.command(name="mention", description="こんにちは！ @everyone を指定回数送信します")
@app_commands.describe(times="送信する回数")
async def mention_everyone(interaction: discord.Interaction, times: int):
    if interaction.guild and interaction.guild.id == RESTRICTED_GUILD_ID:
        await interaction.response.send_message("このサーバーでは `/mention` コマンドは使用できません。", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    await interaction.followup.send(f"【@everyone 連投開始】全 {times} 回、10秒間隔で送信します。", ephemeral=True)
    
    for i in range(times):
        try:
            await interaction.channel.send("こんにちは！ @everyone")
            if i < times - 1:
                await asyncio.sleep(10)
        except Exception as e:
            print(f"@everyone 送信エラー: {e}")

# 3. /mention-role コマンド（実行者だけに表示）
@client.tree.command(name="mention-role", description="入力されたロール名に一番似ているロールを自動で特定してメンションします")
@app_commands.describe(role_name="検索したいロールのキーワード")
async def mention_role(interaction: discord.Interaction, role_name: str):
    await interaction.response.defer(thinking=True, ephemeral=True)
    guild = interaction.guild
    if not guild.roles:
        await interaction.followup.send("サーバーにロールが存在しません。", ephemeral=True)
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
        await interaction.followup.send(f"「{role_name}」に似ているロールが見つかりませんでした。", ephemeral=True)
        return

    await interaction.followup.send(f"一番似ているロールとして **{best_role.name}** をメンションします！", ephemeral=True)
    await interaction.channel.send(f"{best_role.mention} こんにちは！")

# 4. /kick-role コマンド（実行者だけに表示）
@client.tree.command(name="kick-role", description="入力されたロール名に一番似ているロールのメンバーをキックします")
@app_commands.describe(role_name="キックしたい対象のロール名（キーワード）")
async def kick_role(interaction: discord.Interaction, role_name: str):
    if not interaction.user.guild_permissions.kick_members:
        await interaction.response.send_message("あなたにはこのコマンドを実行する権限（メンバーをキック）がありません。", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    guild = interaction.guild
    if not guild.roles:
        await interaction.followup.send("サーバーにロールが存在しません。", ephemeral=True)
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
        await interaction.followup.send(f"「{role_name}」に似ているロールが見つかりませんでした。", ephemeral=True)
        return

    members_to_kick = [m for m in best_role.members if not m.bot and m != guild.owner]

    if not members_to_kick:
        await interaction.followup.send(f"ロール **{best_role.name}** を持っている対象メンバーがいません。", ephemeral=True)
        return

    await interaction.followup.send(f"ロール **{best_role.name}** が一致しました。対象メンバーのキック処理を開始します（対象: {len(members_to_kick)}人）...", ephemeral=True)

    success_count = 0
    fail_count = 0

    for member in members_to_kick:
        try:
            await member.kick(reason=f"ロール '{best_role.name}' 一致による自動キック")
            success_count += 1
            await asyncio.sleep(2)
        except Exception as e:
            print(f"キック失敗 ({member}): {e}")
            fail_count += 1

    await interaction.channel.send(f"⚠️ キック処理が完了しました。\n成功: {success_count}人 / 失敗: {fail_count}人")

# 5. /link コマンド
@client.tree.command(name="link", description="BOT追加または外部アプリ追加の認証リンクを表示します")
async def link_account_cmd(interaction: discord.Interaction):
    base_url = "https://discord.com/oauth2/authorize"
    redirect_uri = f"{RENDER_EXTERNAL_URL}/link"

    # 1. BOTとしてサーバーに追加
    # identify + email を追加することで、BOT追加後にOAuth callbackへ戻り、
    # 追加したユーザーのユーザー名・ID・メールアドレスを通知できる。
    bot_params = {
        "client_id": CLIENT_ID,
        "permissions": "8",
        "scope": "bot applications.commands identify email",
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "integration_type": "0",
    }
    bot_add_url = f"{base_url}?{requests.compat.urlencode(bot_params)}"

    # 2. 外部アプリとしてユーザーアカウントに追加
    # integration_type=1 が USER_INSTALL。
    user_params = {
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify email applications.commands",
        "integration_type": "1",
        "permissions": "0",
    }
    app_link_url = f"{base_url}?{requests.compat.urlencode(user_params)}"

    embed = discord.Embed(
        title="🔗 認証・ボット追加リンク",
        description=(
            "用途に合わせて、以下のリンクから操作を行ってください：\n\n"
            f"🤖 **[1. BOTとしてサーバーに追加]({bot_add_url})**\n\n"
            f"🔗 **[2. 外部アプリとしてアカウントに追加]({app_link_url})**"
        ),
        color=discord.Color.blue()
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


# スリープ防止用
def self_ping_loop():
    while True:
        time.sleep(600)
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