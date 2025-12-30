from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import re

# === CONFIGURATION ===
TOKEN = "8544742650:AAFasnr1UxxAdgphfLeXr-QrpQk_w16sd4c"

# Google Sheets setup
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
client = gspread.authorize(CREDS)
sheet = client.open("HallDash Orders").sheet1

# Canva menu image (your uploaded image URL)
MENU_IMAGE_URL = "Menu.png"

# Menu items and prices
ITEMS = {
    "Samyang Buldak Ramen - Carbonara": 4,
    "Samyang Buldak Ramen - Original": 4,
    "Milo Iced Energy": 2,
    "Monster Energy - Green Apple": 3,
    "Monster Energy - Mango": 3,
    "Monster Energy - White": 3,
    "Nescafe Can - Latte": 2,
    "Nescafe Can - Mocha": 2,
    "Nescafe Can - Original": 2,
    "Tissue Box": 4,
    "Toothbrush Kit": 3,
    "Shampoo": 10
}


# === STATE TRACKING ===
user_states = {}

# === HELPER FUNCTIONS ===
def format_cart(cart):
    if not cart:
        return "Your cart is empty."
    lines = [f"{item} x {qty} (${ITEMS[item]*qty})" for item, qty in cart.items()]
    total = sum(ITEMS[item]*qty for item, qty in cart.items())
    lines.append(f"\nTotal: ${total}")
    return "\n".join(lines)

def save_cart(username, cart, location):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cart_items = ", ".join([f"{item} x{qty}" for item, qty in cart.items()])
    total = sum(ITEMS[item]*qty for item, qty in cart.items())
    sheet.append_row([timestamp, username, cart_items, total, location])
    print(f"Saved order: {username} - {cart_items} - {location}")

# === COMMAND HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome to HallDash! Type /order to see our menu.")

async def order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = {"step": "choose_item", "cart": {}}

    # Send Canva menu image once
    await update.message.reply_photo(
        photo=MENU_IMAGE_URL,
        caption="🍽️ *HallDash Menu*\n\nTap an item below to order:",
        parse_mode="Markdown"
    )

    # Inline button menu
    buttons = [
        [InlineKeyboardButton(f"{item} — ${price}", callback_data=item)]
        for item, price in ITEMS.items()
    ]
    buttons.append([InlineKeyboardButton("🛒 Finish Cart", callback_data="finish_cart")])
    buttons.append([InlineKeyboardButton("🗑 Remove Item", callback_data="remove_item")])
    reply_markup = InlineKeyboardMarkup(buttons)

    await update.message.reply_text("Select an item:", reply_markup=reply_markup)

#=== CALLBACK HANDLER (when user taps a button) ===
async def handle_item_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # ✅ Acknowledge callback immediately (removes button lag)

    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.full_name

    # Initialize user state quickly
    state = user_states.setdefault(user_id, {"step": "choose_item", "cart": {}})
    data = query.data


    # Helper: build main menu keyboard once (reused below)
    def build_main_menu():
        buttons = [
            [InlineKeyboardButton(f"{item} — ${price}", callback_data=item)]
            for item, price in ITEMS.items()
        ]
        buttons += [
            [InlineKeyboardButton("🛒 Finish Cart", callback_data="finish_cart")],
            [InlineKeyboardButton("🗑 Remove Item", callback_data="remove_item")]
        ]
        return InlineKeyboardMarkup(buttons)

    # ✅ Option 1: Finish cart
    if data == "finish_cart":
        if not state["cart"]:
            await query.message.edit_text("🛒 Your cart is empty! Add something first.")
            return
        state["step"] = "get_location"
        await query.message.edit_text(
            f"✅ Your cart so far:\n{format_cart(state['cart'])}\n\n📍 Please send your delivery location."
        )
        return

    # ✅ Option 2: Remove item menu
    if data == "remove_item":
        if not state["cart"]:
            await query.message.edit_text("🛍️ Your cart is empty! Nothing to remove.")
            return

        remove_buttons = [
            [InlineKeyboardButton(f"❌ {item}", callback_data=f"remove_{item}")]
            for item in state["cart"].keys()
        ]
        remove_buttons.append([InlineKeyboardButton("⬅ Back", callback_data="back_to_menu")])
        remove_markup = InlineKeyboardMarkup(remove_buttons)

        await query.message.edit_text(
            f"Select an item to remove:\n{format_cart(state['cart'])}",
            reply_markup=remove_markup
        )
        return

    # ✅ Option 3: Remove selected item
    if data.startswith("remove_"):
        item_to_remove = data.removeprefix("remove_")
        if item_to_remove in state["cart"]:
            del state["cart"][item_to_remove]
            msg = f"Removed {item_to_remove}.\n\n🛍️ Current cart:\n{format_cart(state['cart'])}"
        else:
            msg = "That item was not found in your cart."

        await query.message.edit_text(msg, reply_markup=build_main_menu())
        return

    # ✅ Option 4: Back to menu
    if data == "back_to_menu":
        await query.message.edit_text(
            "Back to menu. Select an item:",
            reply_markup=build_main_menu()
        )
        return

    # ✅ Option 5: Item selected
    item = data
    state["current_item"] = item
    state["step"] = "choose_quantity"

    # Edit existing message instead of sending a new one
    await query.message.edit_text(
        f"How many *{item}* would you like?",
        parse_mode="Markdown"
    )

# === TEXT HANDLER (quantity or location) ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name
    text = update.message.text.strip()

    if user_id not in user_states:
        await update.message.reply_text("Type /order to start ordering.")
        return

    state = user_states[user_id]

    # Step: choose quantity
    if state["step"] == "choose_quantity":
        if not re.match(r"^\d+$", text):
            await update.message.reply_text("Please enter a valid number.")
            return
        quantity = int(text)
        item = state["current_item"]
        state["cart"][item] = state["cart"].get(item, 0) + quantity
        state["step"] = "choose_item"

        # Rebuild inline menu
        buttons = [
            [InlineKeyboardButton(f"{item} — ${price}", callback_data=item)]
            for item, price in ITEMS.items()
        ]
        buttons.append([InlineKeyboardButton("🛒 Finish Cart", callback_data="finish_cart")])
        buttons.append([InlineKeyboardButton("🗑 Remove Item", callback_data="remove_item")])
        reply_markup = InlineKeyboardMarkup(buttons)

        await update.message.reply_text(
            f"Added {quantity} x {item}.\n\n🛍️ Current cart:\n{format_cart(state['cart'])}\n\nSelect another item or finish your order.",
            reply_markup=reply_markup
        )
        return

    # Step: get location
    if state["step"] == "get_location":
        location = text
        save_cart(username, state["cart"], location)
        await update.message.reply_photo(
            photo="PayNow QR.jpg",
            caption=f"✅ Order confirmed!\n\nItems:\n{format_cart(state['cart'])}\nLocation: {location}\n\nPlease pay the total amount via PayNow using the QR code above. Thank you for ordering with HallDash!.\n\nPlease complete payment to PayNow within 5mins."
        )
        del user_states[user_id]
        return

# === ERROR HANDLER ===
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Error: {context.error}")

# === MAIN ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("order", order))
    app.add_handler(CallbackQueryHandler(handle_item_selection))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    print("Bot is running...")
    app.run_polling(poll_interval=1)
