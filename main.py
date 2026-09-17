import os
import json
import asyncio
import threading
from typing import Union, Optional
import discord
from discord import app_commands
from flask import Flask

# ═══════════════════ CẤU HÌNH CHUNG ═══════════════════
TOKEN = os.getenv("DISCORD_TOKEN", "")   # Token từ biến môi trường (an toàn trên GitHub/Render)

DEFAULT_GIF     = "https://i.pinimg.com/originals/78/17/b2/7817b2cf90b9144bc972b7950a9aebf3.gif"
DEFAULT_POLICY  = "https://discord.com"
EMBED_COLOR     = 0x0B0B0B
CONFIG_FILE     = "config.json"          # Lưu cài đặt RIÊNG của từng server

if not TOKEN:
    raise SystemExit("⚠️ Chưa set biến môi trường DISCORD_TOKEN!")

intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# ═════════════ WEB SERVER GIỮ BOT SỐNG 24/7 (Render) ═════════════
web = Flask(__name__)

@web.route("/")
def home():
    return f"✅ Ticket Bot đang chạy 24/7 tại {len(bot.guilds)} server!"

def run_web():
    web.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

threading.Thread(target=run_web, daemon=True).start()


# ═════════════ LƯU/ĐỌC CONFIG THEO TỪNG SERVER ═════════════
def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config() -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, ensure_ascii=False, indent=2)

CONFIG = load_config()

def get_cfg(guild_id: int) -> dict:
    return CONFIG.get(str(guild_id), {})


# ═════════════ TIỆN ÍCH ═════════════
def black_embed(title: str = None, description: str = None) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=EMBED_COLOR)

def is_staff(member: discord.Member) -> bool:
    p = member.guild_permissions
    if p.administrator or p.manage_guild or p.manage_channels:
        return True
    cfg = get_cfg(member.guild.id)
    ids = [cfg.get("admin_role_id"), cfg.get("support_role_id")]
    return any(member.get_role(r) for r in ids if r)

def get_category(guild: discord.Guild):
    cid = get_cfg(guild.id).get("category_id")
    if not cid:
        return None
    ch = guild.get_channel(cid)
    if isinstance(ch, discord.TextChannel):
        return ch.category
    if isinstance(ch, discord.CategoryChannel):
        return ch
    return None

def get_ping_roles(guild: discord.Guild):
    """Role Admin + Support Mod của server đó (theo config, fallback theo tên)."""
    cfg = get_cfg(guild.id)
    roles = []
    for rid in (cfg.get("admin_role_id"), cfg.get("support_role_id")):
        if rid:
            r = guild.get_role(rid)
            if r and r not in roles:
                roles.append(r)
    if roles:
        return roles
    # Fallback: tự tìm role tên có admin/support/mod
    for r in guild.roles:
        if r.is_default() or r.managed:
            continue
        n = r.name.lower()
        if "admin" in n or "support" in n or "mod" in n:
            roles.append(r)
        if len(roles) >= 2:
            break
    return roles


# ═════════════ EMBED ═════════════
def panel_embed(guild: discord.Guild) -> discord.Embed:
    cfg = get_cfg(guild.id)
    e = black_embed(
        title="🔥 HỖ TRỢ KHÁCH HÀNG",
        description=(
            "**🛒 MUA HÀNG:**\n"
            "Nếu bạn muốn mua key bản quyền hoặc dịch vụ tối ưu PC\n\n"
            "**⚙️ HỖ TRỢ:**\n"
            "Nếu bạn cần kích hoạt key, cài đặt, bảo hành hoặc gặp lỗi sau khi mua\n\n"
            "✦ Vui lòng không spam ticket\n"
            "✦ Khách hàng là thượng đế\n"
            "✦ Mua hàng = chấp nhận Rules & Chính sách mà Shop đưa ra"
        ),
    )
    e.set_image(url=cfg.get("gif_url") or DEFAULT_GIF)
    e.set_footer(text=f"{guild.name} • TICKET SUPPORT CENTER")
    return e

def ticket_embed(guild: discord.Guild, user: discord.Member, loai: str) -> discord.Embed:
    cfg = get_cfg(guild.id)
    e = black_embed(
        title=f"🎟️ TICKET {loai}",
        description=(
            f"Xin chào {user.mention}, chào mừng đến với ticket!\n\n"
            "📝 Vui lòng mô tả **chi tiết vấn đề** của bạn để staff hỗ trợ nhanh nhất.\n\n"
            "✦ Không spam / ping staff liên tục\n"
            "✦ Không chia sẻ thông tin cá nhân\n"
            "✦ Staff sẽ phản hồi trong ít phút"
        ),
    )
    e.set_thumbnail(url=user.display_avatar.url)
    e.set_image(url=cfg.get("gif_url") or DEFAULT_GIF)
    e.set_footer(text=f"{guild.name} • TICKET SUPPORT CENTER")
    return e


# ═════════════ TẠO TICKET (MỖI SERVER DÙNG CONFIG RIÊNG) ═════════════
async def open_ticket(interaction: discord.Interaction, slug: str, loai: str):
    try:
        await _open_ticket_impl(interaction, slug, loai)
    except Exception as e:
        print("❌ Lỗi open_ticket:", e)
        msg = black_embed(description=f"❌ Đã xảy ra lỗi: `{e}`")
        if interaction.response.is_done():
            await interaction.followup.send(embed=msg, ephemeral=True)
        else:
            await interaction.response.send_message(embed=msg, ephemeral=True)

async def _open_ticket_impl(interaction: discord.Interaction, slug: str, loai: str):
    guild, user = interaction.guild, interaction.user
    category = get_category(guild)

    if not category:
        return await interaction.response.send_message(
            embed=black_embed(description="⚠️ Server này chưa cài đặt! Admin hãy gõ `/setup` trước."),
            ephemeral=True)

    for ch in category.text_channels:
        if ch.topic and ch.topic.startswith(f"ticket|{user.id}|"):
            return await interaction.response.send_message(
                embed=black_embed(description=f"❌ Bạn đã có ticket mở: {ch.mention}"),
                ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    ping_roles = get_ping_roles(guild)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            attach_files=True, embed_links=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    for role in ping_roles:
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True)
    for role in guild.roles:
        if role.is_default():
            continue
        perms = role.permissions
        if perms.administrator or perms.manage_guild or perms.manage_channels:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True)

    try:
        channel = await guild.create_text_channel(
            name=f"{slug}-{user.name}", category=category,
            topic=f"ticket|{user.id}|{slug}", overwrites=overwrites,
            reason=f"Ticket {loai} - {user}")
    except discord.Forbidden:
        return await interaction.followup.send(
            embed=black_embed(description="❌ Bot thiếu quyền **Manage Channels / Manage Roles**!"),
            ephemeral=True)

    mention_staff = " ".join(r.mention for r in ping_roles)
    content = user.mention + (f" • {mention_staff}" if mention_staff else "")
    await channel.send(content, embed=ticket_embed(guild, user, loai), view=TicketControl())
    await interaction.followup.send(
        embed=black_embed(description=f"✅ Ticket của bạn: {channel.mention}"),
        ephemeral=True)


# ═════════════ FORM LÝ DO ĐÓNG TICKET ═════════════
class CloseReasonModal(discord.ui.Modal, title="🔒 Đóng Ticket"):
    ly_do = discord.ui.TextInput(
        label="Lý do đóng ticket (có thể bỏ trống)",
        style=discord.TextStyle.paragraph,
        placeholder="VD: Đã hỗ trợ xong / Đã bán hàng...",
        required=False, max_length=300)

    async def on_submit(self, interaction: discord.Interaction):
        staff = " ".join(r.mention for r in get_ping_roles(interaction.guild))
        desc = (
            f"**📝 Lý do:** {self.ly_do.value or '*Không có lý do*'}\n"
            f"**👤 Người đóng:** {interaction.user.mention}\n"
            + (f"**🔔 Thông báo:** {staff}\n" if staff else "")
            + "\nBạn có chắc muốn đóng ticket này?"
        )
        await interaction.response.send_message(
            embed=black_embed(title="⚠️ XÁC NHẬN ĐÓNG TICKET", description=desc),
            view=ConfirmClose())


# ═════════════ NÚT TRONG TICKET ═════════════
class TicketControl(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="NHẬN XỬ LÝ", emoji="🙋", style=discord.ButtonStyle.secondary, custom_id="ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff(interaction.user):
            return await interaction.response.send_message(
                embed=black_embed(description="❌ Chỉ người có quyền quản lý mới nhận được ticket!"),
                ephemeral=True)
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(
            embed=black_embed(description=f"🙋 {interaction.user.mention} đã nhận ticket. Vui lòng chờ!"))

    @discord.ui.button(label="ĐÓNG TICKET", emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CloseReasonModal())


class ConfirmClose(discord.ui.View):
    @discord.ui.button(label="XÁC NHẬN ĐÓNG", emoji="🔒", style=discord.ButtonStyle.secondary)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=black_embed(description="🔒 Ticket sẽ bị **xóa sau 5 giây**..."))
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason="Ticket đã đóng")
        except Exception as e:
            print("❌ Lỗi xóa kênh:", e)

    @discord.ui.button(label="HỦY", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()


# ═════════════ PANEL (DÙNG CHUNG CHO MỌI SERVER) ═════════════
class TicketPanel(discord.ui.View):
    def __init__(self, policy_link: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="CHÍNH SÁCH MUA HÀNG", emoji="📜",
            style=discord.ButtonStyle.link, url=policy_link))

    @discord.ui.button(label="MUA HÀNG", emoji="🛒", style=discord.ButtonStyle.secondary, custom_id="ticket_buy")
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_ticket(interaction, "mua-hang", "MUA HÀNG")

    @discord.ui.button(label="HỖ TRỢ", emoji="⚙️", style=discord.ButtonStyle.secondary, custom_id="ticket_support")
    async def support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_ticket(interaction, "ho-tro", "HỖ TRỢ")


# ═════════════ LỆNH /setup — CÀI ĐẶT CHO SERVER NÀY ═════════════
@tree.command(name="setup", description="⚙️ Cài đặt ticket cho server này (chỉ admin)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    category="Category sẽ chứa các kênh ticket",
    admin_role="Role Admin (được tag khi tạo ticket)",
    support_role="Role Support Mod (được tag khi tạo ticket)",
    gif_url="(Tuỳ chọn) Link GIF banner riêng cho server này",
    policy_link="(Tuỳ chọn) Link nút CHÍNH SÁCH MUA HÀNG")
async def setup(interaction: discord.Interaction,
                category: Union[discord.CategoryChannel, discord.TextChannel],
                admin_role: Optional[discord.Role] = None,
                support_role: Optional[discord.Role] = None,
                gif_url: Optional[str] = None,
                policy_link: Optional[str] = None):
    cfg = CONFIG.setdefault(str(interaction.guild_id), {})
    cfg["category_id"] = category.id if isinstance(category, discord.CategoryChannel) else category.category_id
    cfg["admin_role_id"] = admin_role.id if admin_role else 0
    cfg["support_role_id"] = support_role.id if support_role else 0

    if gif_url and gif_url.startswith("http"):
        cfg["gif_url"] = gif_url
    if policy_link and policy_link.startswith("http"):
        cfg["policy_link"] = policy_link

    save_config()

    roles_txt = []
    if admin_role:   roles_txt.append(f"{admin_role.mention} (Admin)")
    if support_role: roles_txt.append(f"{support_role.mention} (Support)")
    tag_txt = " • ".join(roles_txt) if roles_txt else "*tự tìm role tên Admin/Support/Mod*"

    await interaction.response.send_message(
        embed=black_embed(
            title="✅ ĐÃ CÀI ĐẶT TICKET CHO SERVER NÀY!",
            description=(
                f"📁 **Category:** {category.mention if isinstance(category, discord.TextChannel) else category.name}\n"
                f"🔔 **Tag khi tạo ticket:** {tag_txt}\n"
                f"🖼️ **GIF:** {'Riêng của server' if cfg.get('gif_url') else 'Mặc định'}\n\n"
                "👉 Gõ `/panel` để gửi bảng ticket cho khách dùng!")),
        ephemeral=True)

@setup.error
async def setup_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            embed=black_embed(description="❌ Chỉ admin mới dùng được lệnh này!"), ephemeral=True)
    else:
        print("Lỗi /setup:", error)


# ═════════════ LỆNH /panel — GỬI BẢNG TICKET ═════════════
@tree.command(name="panel", description="📩 Gửi panel ticket hỗ trợ (chỉ admin)")
@app_commands.checks.has_permissions(administrator=True)
async def panel(interaction: discord.Interaction):
    cfg = get_cfg(interaction.guild_id)
    if not cfg.get("category_id"):
        return await interaction.response.send_message(
            embed=black_embed(description="⚠️ Chưa cài đặt! Gõ `/setup` trước đã."), ephemeral=True)
    link = cfg.get("policy_link") or DEFAULT_POLICY
    await interaction.response.send_message(embed=panel_embed(interaction.guild), view=TicketPanel(link))

@panel.error
async def panel_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            embed=black_embed(description="❌ Chỉ admin mới dùng được lệnh này!"), ephemeral=True)
    else:
        print("Lỗi /panel:", error)


# ═════════════ LỆNH /ticket — TẠO NGAY ═════════════
@tree.command(name="ticket", description="🎟️ Tạo ticket hỗ trợ ngay lập tức")
@app_commands.describe(loai="Chọn loại ticket (không chọn = HỖ TRỢ)")
@app_commands.choices(loai=[
    app_commands.Choice(name="🛒 MUA HÀNG", value="mua-hang"),
    app_commands.Choice(name="⚙️ HỖ TRỢ", value="ho-tro"),
])
async def ticket(interaction: discord.Interaction, loai: app_commands.Choice[str] = None):
    slug = loai.value if loai else "ho-tro"
    ten  = "MUA HÀNG" if slug == "mua-hang" else "HỖ TRỢ"
    await open_ticket(interaction, slug, ten)


# ═════════════ SỰ KIỆN ═════════════
@bot.event
async def on_ready():
    bot.add_view(TicketPanel(DEFAULT_POLICY))   # view mặc định, link riêng được gửi kèm /panel
    bot.add_view(TicketControl())
    try:
        await tree.sync()                       # sync global → hoạt động mọi server
        print("✅ Đã sync lệnh global!")
    except Exception as e:
        print("Lỗi sync lệnh:", e)
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="Ticket • 24/7"))
    print(f"✅ Bot online: {bot.user} | {len(bot.guilds)} server")

@bot.event
async def on_guild_join(guild: discord.Guild):
    """Bot vừa được mời vào server mới → sync lệnh NGAY cho server đó."""
    try:
        await tree.sync(guild=guild)
        print(f"➕ Tham gia server mới: {guild.name} — đã sync lệnh!")
    except Exception as e:
        print("Lỗi sync server mới:", e)


bot.run(TOKEN)
