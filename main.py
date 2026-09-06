import os
import random
import threading
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import tasks
import requests
from flask import Flask

# ============================================================
# 設定
# ============================================================
# Discord Botトークン（環境変数から読み込み。Renderの「Environment」タブで設定してください）
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")

# アプリケーション（クライアント）ID。/link で招待リンクを作るのに使用
CLIENT_ID = os.environ.get("CLIENT_ID")

# オフライン防止のためにアクセスするURL（Render Web ServiceのURL）
KEEP_ALIVE_URL = os.environ.get("KEEP_ALIVE_URL", "https://arashi-3vci.onrender.com")

# Render用にFlaskがバインドするポート（Renderが自動でPORTを渡してくる）
PORT = int(os.environ.get("PORT", 8080))

# 機能を無効化するサーバーID
DISABLED_GUILD_ID = 1510021467155202048

# /link を使った人の情報を送信するチャンネルID
LINK_LOG_CHANNEL_ID = 1545620371477106868

# ============================================================
# Flask（普通のWebアプリとしても機能させる & Renderのヘルスチェック用）
# ============================================================
app = Flask(__name__)


@app.route("/")
def index():
    return "Bot is alive! ({})".format(datetime.utcnow().isoformat())


@app.route("/health")
def health():
    return {"status": "ok"}


def run_flask():
    # Renderはポートをlistenしていないとサービスが起動しないと判定するため必須
    app.run(host="0.0.0.0", port=PORT)


# ============================================================
# Discord Bot本体
# ============================================================
intents = discord.Intents.default()
intents.members = True  # /bye でロール保持者を取得するために必要（Discord Developer Portalでも有効化が必要）


class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # スラッシュコマンドを同期
        await self.tree.sync()
        # 起こし役（オフライン防止）タスクを開始
        keep_alive_ping.start()


client = MyClient()


@client.event
async def on_ready():
    print(f"ログイン完了: {client.user} (ID: {client.user.id})")


# ------------------------------------------------------------
# 特定サーバーでの機能無効化チェック
# ------------------------------------------------------------
def is_disabled_guild(interaction: discord.Interaction) -> bool:
    return interaction.guild is not None and interaction.guild.id == DISABLED_GUILD_ID


async def guild_disabled_check(interaction: discord.Interaction) -> bool:
    if is_disabled_guild(interaction):
        await interaction.response.send_message(
            "このサーバーではこのBotの機能は無効化されています。", ephemeral=True
        )
        return False
    return True

# ------------------------------------------------------------
# /hello : こんにちは！と言う
# ------------------------------------------------------------
@client.tree.command(name="hello", description="こんにちは！と指定した回数だけ送信します")
@app_commands.describe(count="送る回数を指定してください")
async def hello(interaction: discord.Interaction, count: int):
    await interaction.response.send_message(f"こんにちは @everyone を {count} 回言います", ephemeral=True)
    
    for _ in range(count):
        await interaction.channel.send("**RAID BY ダイヤ作成所** こんにちは！ @here @everyone")

# ------------------------------------------------------------
# /createchannel (個数) : テキストチャンネルを指定個数作成する
# ------------------------------------------------------------
@client.tree.command(name="createchannel", description="指定した個数のテキストチャンネルを作成します")
@app_commands.describe(個数="作成するチャンネルの数")
@app_commands.check(guild_disabled_check)
@app_commands.allowed_installs(guild=True, user=True)
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def createchannel(interaction: discord.Interaction, 個数: int):
    if interaction.guild is None:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)
        return

    if 個数 <= 0:
        await interaction.response.send_message("1個以上の数を指定してください。", ephemeral=True)
        return

    if 個数 > 50:
        await interaction.response.send_message("一度に作成できるのは50個までです。", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    created = []
    for i in range(1, 個数 + 1):
        channel = await interaction.guild.create_text_channel(name=f"新しいチャンネル-{i}")
        created.append(channel.name)

    await interaction.followup.send(f"{個数}個のチャンネルを作成しました:\n" + "\n".join(created))


# ------------------------------------------------------------
# /bye [roleID] : 指定したロールIDを持つ人をキックする
# ------------------------------------------------------------
@client.tree.command(name="bye", description="指定したロールを持つメンバーをキックします")
@app_commands.describe(roleid="キック対象のロールID")
@app_commands.check(guild_disabled_check)
@app_commands.allowed_installs(guild=True, user=True)
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def bye(interaction: discord.Interaction, roleid: str):
    if interaction.guild is None:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    if not interaction.user.guild_permissions.kick_members:
        await interaction.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)
        return

    try:
        role_id_int = int(roleid)
    except ValueError:
        await interaction.response.send_message("ロールIDは数字で入力してください。", ephemeral=True)
        return

    role = interaction.guild.get_role(role_id_int)
    if role is None:
        await interaction.response.send_message("指定されたロールIDが見つかりません。", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    kicked = []
    failed = []
    for member in role.members:
        try:
            await member.kick(reason=f"/bye コマンドによるロール({role.name})保持者のキック")
            kicked.append(member.display_name)
        except discord.Forbidden:
            failed.append(member.display_name)
        except discord.HTTPException:
            failed.append(member.display_name)

    msg = f"ロール「{role.name}」保持者 {len(kicked)}人をキックしました。"
    if kicked:
        msg += "\n" + "、".join(kicked)
    if failed:
        msg += "\n\n以下のメンバーはキックに失敗しました:\n" + "、".join(failed)

    await interaction.followup.send(msg)

# ------------------------------------------------------------
# /random-hello : サーバー内から指定した人数をランダムに選んで「こんにちは！」と言う
# ------------------------------------------------------------
@client.tree.command(name="random-hello", description="サーバー内から指定した人数をランダムに選んでこんにちは！と言います")
@app_commands.describe(count="選ぶ人数を指定してください")
@app_commands.check(guild_disabled_check)
@app_commands.allowed_installs(guild=True, user=True)
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def random_hello(interaction: discord.Interaction, count: int):
    if interaction.guild is None:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    # Bot以外のメンバーを対象にする
    candidates = [m for m in interaction.guild.members if not m.bot]

    if len(candidates) < count:
        await interaction.response.send_message(
            f"ランダムに選べるメンバーが {count} 人未満です（現在の候補者数: {len(candidates)}人）。",
            ephemeral=True,
        )
        return

    chosen = random.sample(candidates, count)
    mentions = " ".join([m.mention for m in chosen])
    await interaction.response.send_message(f"こんにちは！ {mentions}")
# ------------------------------------------------------------
# /link : Botをサーバー追加 or 外部アプリ（個人）として追加するリンクを表示
#          実行者のユーザー名・ユーザーID・導入先を指定チャンネルへ記録
#          （メールアドレスなどDiscordが提供しない情報は取得・記録しません）
# ------------------------------------------------------------
@client.tree.command(name="link", description="このBotをサーバーまたは外部アプリとして追加するリンクを表示します")
@app_commands.check(guild_disabled_check)
@app_commands.allowed_installs(guild=True, user=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def link(interaction: discord.Interaction):
    if not CLIENT_ID:
        await interaction.response.send_message(
            "現在、招待リンクを発行できません（CLIENT_IDが未設定です）。管理者にご連絡ください。",
            ephemeral=True,
        )
        return

    # Bot（サーバー追加）用の権限: チャンネル管理 + メンバーキック
    bot_permissions = discord.Permissions(manage_channels=True, kick_members=True)
    bot_invite_url = discord.utils.oauth_url(
        CLIENT_ID,
        permissions=bot_permissions,
        scopes=("bot", "applications.commands"),
    )

    # 外部アプリ（ユーザーインストール）用リンク
    user_install_url = (
        f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}"
        f"&integration_type=1&scope=applications.commands"
    )

    embed = discord.Embed(title="Botの追加方法を選んでください")
    embed.add_field(name="サーバーにBotとして追加", value=f"[こちらから追加]({bot_invite_url})", inline=False)
    embed.add_field(name="外部アプリ（個人）として追加", value=f"[こちらから追加]({user_install_url})", inline=False)
    embed.set_footer(text="このコマンドを使用すると、あなたのユーザー名・ユーザーID・導入先が運営記録用チャンネルに送信されます（メールアドレス等は取得しません）。")

    await interaction.response.send_message(embed=embed, ephemeral=True)

    # 導入先の判定
    if interaction.guild is not None:
        destination = f"サーバー: {interaction.guild.name} (ID: {interaction.guild.id})"
    else:
        destination = "DM / 個人（外部アプリ）として実行"

    # ログチャンネルへ送信
    log_channel = client.get_channel(LINK_LOG_CHANNEL_ID)
    if log_channel is None:
        try:
            log_channel = await client.fetch_channel(LINK_LOG_CHANNEL_ID)
        except discord.HTTPException:
            log_channel = None

    if log_channel is not None:
        log_embed = discord.Embed(title="/link 使用ログ")
        log_embed.add_field(name="ユーザー名", value=str(interaction.user), inline=False)
        log_embed.add_field(name="ユーザーID", value=str(interaction.user.id), inline=False)
        log_embed.add_field(name="導入先", value=destination, inline=False)
        try:
            await log_channel.send(embed=log_embed)
        except discord.HTTPException as e:
            print(f"[link] ログ送信失敗: {e}")


# ============================================================
# オフライン防止: 10分ごとにKEEP_ALIVE_URLへアクセスして起こす
# ============================================================
@tasks.loop(minutes=10)
async def keep_alive_ping():
    try:
        res = requests.get(KEEP_ALIVE_URL, timeout=10)
        print(f"[keep_alive] {KEEP_ALIVE_URL} -> status {res.status_code}")
    except Exception as e:
        print(f"[keep_alive] アクセス失敗: {e}")


@keep_alive_ping.before_loop
async def before_keep_alive_ping():
    await client.wait_until_ready()


# ============================================================
# エントリーポイント
# ============================================================
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("環境変数 DISCORD_TOKEN が設定されていません。")

    # Flaskを別スレッドで起動（Render Web Serviceとしてポートを開けておくため）
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Discord Botを起動
    client.run(DISCORD_TOKEN)
