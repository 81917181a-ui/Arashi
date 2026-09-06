import os
import threading
import asyncio
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

# オフライン防止のためにアクセスするURL（Render Web ServiceのURL）
KEEP_ALIVE_URL = os.environ.get("KEEP_ALIVE_URL", "https://arashi-3vci.onrender.com")

# Render用にFlaskがバインドするポート（Renderが自動でPORTを渡してくる）
PORT = int(os.environ.get("PORT", 8080))

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
# /hello : こんにちは！と言う
# ------------------------------------------------------------
@client.tree.command(name="hello", description="こんにちは！と指定した回数だけ送信します")
@app_commands.describe(count="送る回数を指定してください")
async def hello(interaction: discord.Interaction, count: int):
    await interaction.response.send_message(f"こんにちは @everyone を {count} 回言います", ephemeral=True)
    
    for _ in range(count):
        await interaction.channel.send("こんにちは！ @everyone")


# ------------------------------------------------------------
# /createchannel (個数) : テキストチャンネルを指定個数作成する
# ------------------------------------------------------------
@client.tree.command(name="createchannel", description="指定した個数のテキストチャンネルを作成します")
@app_commands.describe(個数="作成するチャンネルの数")
async def createchannel(interaction: discord.Interaction, 個数: int):
    # サーバー内でのみ使用可能
    if interaction.guild is None:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    # 権限チェック（チャンネル管理権限を持つユーザーのみ実行可）
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
async def bye(interaction: discord.Interaction, roleid: str):
    if interaction.guild is None:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    # 権限チェック（メンバーキック権限を持つユーザーのみ実行可）
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
        msg += f"\n\n以下のメンバーはキックに失敗しました:\n" + "、".join(failed)

    await interaction.followup.send(msg)


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
