import sqlite3
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext
from telegram.error import BadRequest

# 🚀 Replace with your details
TOKEN = "token"
PAY_PER_REFERRAL = 1  # ₹1 per subscriber
PRICE_PLANS = {500: 2, 1000: 1.8, 5000: 1.5}  # Custom pricing per subscriber count
MIN_WITHDRAWAL = 50  # Minimum withdrawal for users
ADMIN_ID = "admin id"
UPI_ID = "bank@upi"

# 📌 Initialize database
conn = sqlite3.connect("referrals.db", check_same_thread=False)
c = conn.cursor()

# Create tables
c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        referrals INTEGER DEFAULT 0,
        balance INTEGER DEFAULT 0
    )
""")
c.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        channel_link TEXT,
        target_subs INTEGER,
        amount INTEGER,
        current_subs INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending'
    )
""")
conn.commit()

# 📌 Check if User is Subscribed
async def check_subscription(user_id, channel_link, context):
    try:
        chat_member = await context.bot.get_chat_member(channel_link, user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except BadRequest:
        return False

# 📌 Start Command
async def start(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    username = update.message.from_user.username or f"User{user_id}"
    args = context.args

    # Step 1️⃣: If they came from a referral, credit the referrer
    if args:
        referrer_id = args[0]
        if user_id != int(referrer_id):
            c.execute("UPDATE users SET referrals = referrals + 1, balance = balance + ? WHERE user_id = ?", 
                      (PAY_PER_REFERRAL, referrer_id))
            conn.commit()
            await context.bot.send_message(referrer_id, f"🎉 You earned ₹{PAY_PER_REFERRAL} from your referral!")

    # Step 2️⃣: Save user and send welcome message
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()

    await update.message.reply_text(
        f"""👋 Welcome {username}!\n
         💰 Earn ₹{PAY_PER_REFERRAL} per referral.\n
         📎 Use /referral to get your unique link.\n
         📢 Need subscribers? Use /order.\n
         💳 Pay via UPI: {UPI_ID}"""
    )

# 📌 Generate Referral Link
async def referral(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    
    # Fetch the latest approved order (client’s channel link)
    c.execute("SELECT channel_link FROM orders WHERE status='approved' ORDER BY order_id DESC LIMIT 1")
    order = c.fetchone()

    if order:
        channel_link = order[0]
        await update.message.reply_text(
            f"""🔗 Your referral link:\n\n"
             🚀 Invite users to **{channel_link}**\n
             👥 Earn ₹{PAY_PER_REFERRAL} per referral.\n"
             Share this bot link: https://t.me/TeleBoostxBot?start={user_id}"""
        )
    else:
        await update.message.reply_text("❌ No active referral campaigns at the moment.")

# 📌 Order Command
async def order(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id

    if len(context.args) < 2:
        await update.message.reply_text("❌ Usage: /order <channel_link> <number_of_subs>")
        return

    channel_link = context.args[0]
    target_subs = int(context.args[1])
    price_per_sub = PRICE_PLANS[min(PRICE_PLANS, key=lambda x: abs(x - target_subs))]
    amount = int(target_subs * price_per_sub)
    
    c.execute("INSERT INTO orders (client_id, channel_link, target_subs, amount) VALUES (?, ?, ?, ?)",
              (user_id, channel_link, target_subs, amount))
    conn.commit()

    await update.message.reply_text(
        f"""✅ Order placed for {target_subs} subscribers.\n"
         💰 Total cost: ₹{amount}\n"
         💳 Pay via UPI: {UPI_ID} and send proof to admin.\n"
         📩 Send Screenshot to @AdminUsername"""
    )

# 📌 Withdrawal Command
async def withdraw(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    username = update.message.from_user.username or f"User{user_id}"
    
    # Fetch balance
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    
    if not result:
        await update.message.reply_text("❌ You have no earnings yet.")
        return

    balance = result[0]

    if balance < MIN_WITHDRAWAL:
        await update.message.reply_text(f"❌ Minimum withdrawal is ₹{MIN_WITHDRAWAL}. Your balance: ₹{balance}")
        return

    withdrawal_message = (
        f"""📢 *New Withdrawal Request*\n
         👤 User: @{username} (`{user_id}`)\n
         💰 Amount: ₹{balance}\n"
         ✅ Please approve or reject."""
    )
    
    await update.message.reply_text(f"✅ Withdrawal request for ₹{balance} sent. Admin will review.")
    await context.bot.send_message(ADMIN_ID, withdrawal_message, parse_mode="Markdown")

    c.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
# 📌 Approve Payment Command
async def approve_payment(update: Update, context: CallbackContext):
    if update.message.from_user.id != int(ADMIN_ID):
        await update.message.reply_text("❌ You are not authorized.")
        return

    if len(context.args) < 1:
        await update.message.reply_text("❌ Usage: /approve <order_id>")
        return

    order_id = context.args[0]
    c.execute("SELECT client_id, channel_link, target_subs FROM orders WHERE order_id=? AND status='pending'", (order_id,))
    order = c.fetchone()

    if not order:
        await update.message.reply_text("❌ Order not found or already approved.")
        return

    client_id, channel_link, target_subs = order

    c.execute("UPDATE orders SET status='approved' WHERE order_id=?", (order_id,))
    conn.commit()
    await context.bot.send_message(client_id, f"🎉 Your order for {target_subs} subscribers has been approved! Start referring users now.")
    await update.message.reply_text(f"✅ Order {order_id} approved successfully.")


async def admin_dashboard(update: Update, context: CallbackContext):
    if update.message.from_user.id != int(ADMIN_ID):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    # Get total pending and approved orders
    c.execute("SELECT COUNT(*), SUM(amount) FROM orders WHERE status='pending'")
    total_pending_orders, total_pending_amount = c.fetchone()
    total_pending_amount = total_pending_amount or 0

    c.execute("SELECT COUNT(*), SUM(amount) FROM orders WHERE status='approved'")
    total_active_orders, total_revenue = c.fetchone()
    total_revenue = total_revenue or 0  # Fixed: Revenue should be stored properly

    # Get total users
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]

    # Get total withdrawal requests
    c.execute("SELECT SUM(balance) FROM users WHERE balance >= ?", (MIN_WITHDRAWAL,))
    total_withdrawals = c.fetchone()[0] or 0

    # Fetch pending orders
    c.execute("SELECT order_id, client_id, channel_link, target_subs, amount FROM orders WHERE status='pending'")
    pending_orders = c.fetchall()

    # Fetch active (approved) orders
    c.execute("SELECT order_id, client_id, channel_link, target_subs, amount FROM orders WHERE status='approved'")
    active_orders = c.fetchall()

    # Format order lists
    pending_list = "\n".join([
        f"🆔 Order ID: {o[0]}\n👤 Client: {o[1]}\n🔗 Channel: {o[2]}\n🎯 Target: {o[3]}\n💰 Amount: ₹{o[4]}\n"
        "----------------------" for o in pending_orders
    ]) if pending_orders else "✅ No pending orders."

    active_list = "\n".join([
        f"🆔 Order ID: {o[0]}\n👤 Client: {o[1]}\n🔗 Channel: {o[2]}\n🎯 Target: {o[3]}\n💰 Amount: ₹{o[4]}\n"
        "----------------------" for o in active_orders
    ]) if active_orders else "✅ No active orders."

    # Send admin dashboard message
    await update.message.reply_text(
        f"""📊 *Admin Dashboard*\n
📝 Pending Orders: {total_pending_orders}\n
💰 Total Revenue: ₹{total_revenue}\n
🔄 Withdrawal Requests: ₹{total_withdrawals}\n
👥 Total Users: {total_users}\n
📋 *Pending Orders:* \n{pending_list}\n
📌 *Active Orders:* \n{active_list}\n
✅ Use `/vieworder <order_id>` to see full details."""
    )

    
# 📌 View Order Details (Admin Only)
async def view_order(update: Update, context: CallbackContext):
    if update.message.from_user.id != int(ADMIN_ID):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("❌ Usage: /vieworder <order_id>")
        return

    order_id = context.args[0]

    # Fetch order details
    c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,))
    order = c.fetchone()

    if not order:
        await update.message.reply_text("❌ Order not found.")
        return

    # Extract order details
    order_id, client_id, channel_link, target_subs, amount, current_subs, status = order

    await update.message.reply_text(
        f"""📦 *Order Details*\n
        🆔 Order ID: {order_id}\n
        👤 Client ID: {client_id}\n
        🔗 Channel: {channel_link}\n
        🎯 Target Subscribers: {target_subs}\n
        📊 Current Subscribers: {current_subs}\n
        💰 Amount Paid: ₹{amount}\n
        📌 Status: {status.capitalize()}"""
    )
from telegram import Chat

# 📌 Command to Check Live Subscribers for an Order
async def check_live_subs(update: Update, context: CallbackContext):
    if len(context.args) < 1:
        await update.message.reply_text("❌ Usage: /livesubs <order_id>")
        return

    order_id = context.args[0]

    # Fetch channel link from the order ID
    c.execute("SELECT channel_link FROM orders WHERE order_id = ?", (order_id,))
    result = c.fetchone()

    if not result:
        await update.message.reply_text("❌ Order not found.")
        return

    channel_link = result[0]

    try:
        # Fetch the live subscriber count
        chat = await context.bot.get_chat(channel_link)
        subscriber_count = await chat.get_member_count()

        # Update the current subscriber count in the database
        c.execute("UPDATE orders SET current_subs = ? WHERE order_id = ?", (subscriber_count, order_id))
        conn.commit()

        await update.message.reply_text(
            f"""📢 *Live Subscriber Count*\n
            🆔 Order ID: {order_id}\n
            🔗 Channel: {channel_link}\n
            👥 Subscribers: {subscriber_count}"""
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Error fetching subscriber count: {e}")


# 📌 Set up the bot
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("order", order))
    app.add_handler(CommandHandler("vieworder", view_order))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("approve", approve_payment))
    app.add_handler(CommandHandler("admin", admin_dashboard))
    app.add_handler(CommandHandler("livesubs", check_live_subs))

    
    app.run_polling()

if __name__ == "__main__":
    main()
