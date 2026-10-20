from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import json, os, random, functools, hashlib, time
import threading
import requests

app = Flask(__name__)
app.secret_key = "stream-bet-secret"
DATA_FILE = "stream_bet_data.json"
ADMIN_ID = "031"
BANK_API = "http://127.0.0.1:5001"

@app.after_request
def bypass_localtunnel(response):
    response.headers['Bypass-Tunnel-Reminder'] = 'true'
    return response

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"players": {}, "cards": [], "history": [], "bank": 0, "global_chat": [], "mines_games": {}, "promos": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def hash_pin(pin):
    return hashlib.sha256(("salt_" + pin).encode()).hexdigest()

def get_vip_status(xp):
    if xp >= 100000: return "💎 Платина"
    elif xp >= 30000: return "🥇 Золото"
    elif xp >= 10000: return "🥈 Серебро"
    elif xp >= 1000: return "🥉 Бронза"
    else: return "Новичок"

def add_xp(p, amount):
    p["xp"] = p.get("xp", 0) + (amount // 10)

def spin_roulette():
    number = random.randint(0, 24)
    if number == 0: return number, "зелёный"
    elif number <= 12: return number, "чёрный"
    else: return number, "красный"

def spin_slots():
    symbols = ["🍒", "🍋", "🍇", "💎", "🔔", "7️⃣"]
    return [random.choice(symbols) for _ in range(3)]

def create_mines_game(user_id, bet, mines_count=3):
    indices = list(range(25))
    random.shuffle(indices)
    return {"user_id": user_id, "bet": bet, "mines": mines_count, "bombs": indices[:mines_count], "opened": [], "win": 0, "active": True}

def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "uid" not in session: return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Доступ только для Босса", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

# --- РЕГИСТРАЦИЯ ---
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        pin = request.form.get("pin", "").strip()
        data = load_data()
        if not name or len(pin) < 4:
            flash("Заполните все поля корректно", "error"); return redirect(url_for("register"))
        while True:
            new_id = str(random.randint(1000, 9999))
            if new_id not in data["players"] and new_id != ADMIN_ID: break
        data["players"][new_id] = {"id": new_id, "name": name, "balance": 0, "bank_balance": 0, "xp": 0, "banned": False, "pin": hash_pin(pin), "mask": "Нет"}
        save_data(data)
        flash(f"✅ Аккаунт создан! Ваш ID: {new_id}. Запомните его!", "success"); return redirect(url_for("login"))
    return render_template("register.html")

# --- ВХОД ---
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        uid, pin = request.form.get("uid", "").strip(), request.form.get("pin", "").strip()
        data = load_data()
        if uid == ADMIN_ID:
            if not data.get("admin_pin"):
                data["admin_pin"] = hash_pin(pin); save_data(data)
                flash("PIN Босса установлен.", "success"); return redirect(url_for("login"))
            if hash_pin(pin) != data["admin_pin"]:
                flash("Неверный PIN", "error"); return render_template("login.html")
            session["uid"], session["role"] = uid, "admin"; return redirect(url_for("admin"))
        if uid in data["players"]:
            p = data["players"][uid]
            if p["banned"]: return render_template("login.html", banned=True)
            if not p.get("pin"):
                p["pin"] = hash_pin(pin); save_data(data)
                flash("PIN установлен.", "success"); return redirect(url_for("login"))
            if hash_pin(pin) != p["pin"]:
                flash("Неверный PIN", "error"); return render_template("login.html")
            session["uid"], session["role"] = uid, "player"; return redirect(url_for("player"))
        flash("Игрок не найден", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

# --- API ДЛЯ АДМИНКИ ---
@app.route("/api/admin/players")
def api_admin_players():
    data = load_data()
    return jsonify({"players": data.get("players", {})})

@app.route("/admin/toggle_ban/<pid>")
def toggle_ban(pid):
    data = load_data()
    if pid in data["players"]:
        data["players"][pid]["banned"] = not data["players"][pid].get("banned", False)
        save_data(data)
    return "OK"

@app.route("/admin/create_player", methods=["POST"])
def admin_create_player():
    pid = request.form.get("uid", "").strip()
    name = request.form.get("name", "").strip()
    pin = request.form.get("pin", "").strip()
    data = load_data()
    if pid and name and pin and pid not in data["players"]:
        data["players"][pid] = {"id": pid, "name": name, "balance": 0, "bank_balance": 0, "xp": 0, "banned": False, "pin": hash_pin(pin), "mask": "Нет"}
        save_data(data)
    return "OK"

@app.route("/admin/set_balance", methods=["POST"])
def set_balance():
    pid, target = request.form.get("pid", "").strip(), request.form.get("target", "casino")
    try: amount = int(request.form.get("amount", 0))
    except: return redirect(url_for("admin"))
    data = load_data()
    if pid in data["players"]:
        if target == "bank":
            try:
                requests.post(f"{BANK_API}/api/admin_deposit", json={"uid": pid, "amount": amount}, timeout=2)
                flash(f"✅ Выдано {amount} в StreamBank игроку {pid}", "success")
            except: flash("❌ Банк недоступен", "error")
        else:
            data["players"][pid]["balance"] = max(0, amount)
            save_data(data)
            flash(f"Баланс в Казино игрока {pid} = {amount}", "success")
    return redirect(url_for("admin"))

@app.route("/admin/set_mask", methods=["POST"])
def admin_set_mask():
    uid = request.form.get("uid", "").strip()
    mask = request.form.get("mask", "Нет").strip()
    data = load_data()
    if uid in data["players"]:
        data["players"][uid]["mask"] = mask
        save_data(data)
    return "OK"

# --- ИГРЫ И ЧАТ ---
@app.route("/player")
@login_required
def player():
    data = load_data(); p = data["players"].get(session["uid"])
    if not p: return redirect(url_for("logout"))
    vip = get_vip_status(p.get("xp", 0))
    can_claim_bonus = (time.time() - p.get("last_daily_bonus", 0)) >= 86400
    return render_template("player.html", player=p, vip=vip, bank=data.get("bank", 0), can_claim_bonus=can_claim_bonus)

@app.route("/bank")
@login_required
def bank():
    data = load_data(); p = data["players"].get(session["uid"])
    if not p: return redirect(url_for("logout"))
    try:
        resp = requests.get(f"{BANK_API}/api/balance/{session['uid']}", timeout=2)
        bank_balance = resp.json().get("balance", 0)
    except: bank_balance = 0
    return render_template("bank.html", player=p, bank_balance=bank_balance, bank=data.get("bank", 0))

@app.route("/bank/transfer", methods=["POST"])
@login_required
def bank_transfer():
    data = load_data(); p = data["players"].get(session["uid"])
    action = request.form.get("action")
    try: amount = int(request.form.get("amount", 0))
    except: return redirect(url_for("bank"))
    if amount <= 0: return redirect(url_for("bank"))
    if action == "to_bank" and amount <= p["balance"]:
        p["balance"] -= amount
        try:
            requests.post(f"{BANK_API}/api/transfer", json={"uid": session["uid"], "amount": amount, "action": "add_to_bank"}, timeout=2)
            flash(f"Переведено {amount} в StreamBank", "success")
        except:
            p["balance"] += amount; flash("Банк недоступен", "error")
    elif action == "to_casino":
        try:
            resp = requests.post(f"{BANK_API}/api/transfer", json={"uid": session["uid"], "amount": amount, "action": "take_from_bank"}, timeout=2)
            if resp.json().get("status") == "ok":
                p["balance"] += amount; flash(f"Переведено {amount} из StreamBank", "success")
            else: flash("В банке недостаточно средств", "error")
        except: flash("Банк недоступен", "error")
    save_data(data); return redirect(url_for("bank"))

# --- КРАШ ---
crash_games = {}
def run_crash(game_id):
    time.sleep(2)
    game = crash_games.get(game_id)
    if not game: return
    while game['active']:
        time.sleep(0.1); game['multiplier'] = round(game['multiplier'] + 0.1, 1)
        if game['multiplier'] >= game['crash_point']:
            game['active'] = False; game['crashed'] = True
            data = load_data(); data["bank"] = data.get("bank", 0) + game['bet']; save_data(data)
            break

@app.route("/crash")
@login_required
def crash_page():
    data = load_data(); p = data["players"].get(session["uid"])
    if not p: return redirect(url_for("logout"))
    return render_template("crash.html", player=p, bank=data.get("bank", 0))

@app.route("/crash/start", methods=["POST"])
@login_required
def crash_start():
    data = load_data(); p = data["players"].get(session["uid"])
    if not p or p["banned"]: return redirect(url_for("crash_page"))
    try: bet = int(request.form.get("bet", 0))
    except: return redirect(url_for("crash_page"))
    if bet <= 0 or bet > p["balance"]: flash("Неверная ставка", "error"); return redirect(url_for("crash_page"))
    p["balance"] -= bet; save_data(data)
    game_id = str(session["uid"])
    crash_games[game_id] = {"active": True, "bet": bet, "multiplier": 1.0, "crash_point": round(random.uniform(1.2, 5.0), 1), "crashed": False}
    threading.Thread(target=run_crash, args=(game_id,)).start()
    return redirect(url_for("crash_page"))

@app.route("/api/crash")
@login_required
def api_crash():
    game = crash_games.get(str(session["uid"]))
    if not game: return jsonify({"status": "idle"})
    return jsonify({"status": "active" if game['active'] else "crashed", "multiplier": game['multiplier'], "crashed": game['crashed']})

@app.route("/crash/cashout", methods=["POST"])
@login_required
def crash_cashout():
    data = load_data(); p = data["players"].get(session["uid"])
    game = crash_games.get(str(session["uid"]))
    if not game or not game['active']: return jsonify({"status": "error"})
    win = int(game['bet'] * game['multiplier']); p["balance"] += win; game['active'] = False; save_data(data)
    return jsonify({"status": "ok", "win": win, "multiplier": game['multiplier']})

# --- КОСТИ ---
@app.route("/dice")
@login_required
def dice_page():
    data = load_data(); p = data["players"].get(session["uid"])
    if not p: return redirect(url_for("logout"))
    return render_template("dice.html", player=p, bank=data.get("bank", 0))

@app.route("/dice/roll", methods=["POST"])
@login_required
def dice_roll():
    data = load_data(); p = data["players"].get(session["uid"])
    if not p or p["banned"]: return redirect(url_for("dice_page"))
    try: bet = int(request.form.get("bet", 0))
    except: return redirect(url_for("dice_page"))
    chosen_num = request.form.get("number")
    if bet <= 0 or bet > p["balance"]: flash("Неверная ставка", "error"); return redirect(url_for("dice_page"))
    dice_result = random.randint(1, 6); win = 0
    if str(dice_result) == chosen_num:
        win = bet * 5; p["balance"] += win; flash(f"🎲 Выпало {dice_result}! ВЫ ПОБЕДИЛИ {win} монет!", "success")
    else:
        p["balance"] -= bet; data["bank"] = data.get("bank", 0) + bet; flash(f"🎲 Выпало {dice_result}. Вы проиграли {bet}.", "error")
    data["history"].append({"uid": session["uid"], "game": "dice", "bet": bet, "result": dice_result, "win": win, "time": time.strftime("%H:%M")})
    save_data(data); return redirect(url_for("dice_page"))

# --- ЧАТ ---
@app.route("/api/chat")
@login_required
def api_chat():
    data = load_data(); chat = data.get("global_chat", [])[::-1]
    return jsonify({"chat": chat})

@app.route("/send_message", methods=["POST"])
@login_required
def send_message():
    data = load_data(); p = data["players"].get(session["uid"])
    if not p: return jsonify({"status": "error"})
    msg_text = request.form.get("message", "").strip()
    if msg_text:
        if len(msg_text) > 50: msg_text = msg_text[:50] + "..."
        if "global_chat" not in data: data["global_chat"] = []
        data["global_chat"].append({"time": time.strftime("%H:%M"), "text": msg_text, "author": p['name'], "mask": p.get("mask", ""), "is_admin": session.get("role") == "admin"})
        data["global_chat"] = data["global_chat"][-30:] 
        save_data(data)
    return jsonify({"status": "ok"})

# --- РУЛЕТКА, СЛОТЫ, МИНЫ ---
@app.route("/roulette")
@login_required
def roulette():
    data = load_data(); p = data["players"].get(session["uid"])
    if not p: return redirect(url_for("logout"))
    my_history = [h for h in data.get("history", []) if h["uid"] == session["uid"] and h.get("game") != "slots"][-10:][::-1]
    vip = get_vip_status(p.get("xp", 0)); chat = data.get("global_chat", [])[::-1]
    return render_template("roulette.html", player=p, vip=vip, history=my_history, chat=chat)

@app.route("/spin", methods=["POST"])
@login_required
def spin():
    data = load_data(); p = data["players"].get(session["uid"])
    if not p or p["banned"]: return redirect(url_for("roulette"))
    try: bet = int(request.form.get("bet", 0))
    except: return redirect(url_for("roulette"))
    color = request.form.get("color")
    if bet <= 0 or bet > p["balance"] or color not in ("чёрный", "красный", "зелёный"):
        flash("Неверная ставка", "error"); return redirect(url_for("roulette"))
    add_xp(p, bet); number, real_color = spin_roulette(); win = 0
    if real_color == color:
        win = bet * (14 if color == "зелёный" else 2); p["balance"] += win
    else:
        p["balance"] -= bet; data["bank"] = data.get("bank", 0) + bet
    data["history"].append({"uid": session["uid"], "game": "roulette", "bet": bet, "color": color, "number": number, "real_color": real_color, "win": win, "time": time.strftime("%H:%M")})
    save_data(data)
    return render_template("result.html", number=number, real_color=real_color, chosen=color, win=win, bet=bet, player=p)

@app.route("/slots")
@login_required
def slots():
    data = load_data(); p = data["players"].get(session["uid"])
    if not p: return redirect(url_for("logout"))
    slots_history = [h for h in data.get("history", []) if h["uid"] == session["uid"] and h.get("game") == "slots"][-5:][::-1]
    vip = get_vip_status(p.get("xp", 0)); chat = data.get("global_chat", [])[::-1]
    return render_template("slots.html", player=p, vip=vip, history=slots_history, chat=chat)

@app.route("/slots/spin", methods=["POST"])
@login_required
def slots_spin():
    data = load_data(); p = data["players"].get(session["uid"])
    if not p or p["banned"]: return redirect(url_for("slots"))
    try: bet = int(request.form.get("bet", 0))
    except: return redirect(url_for("slots"))
    if bet <= 0 or bet > p["balance"]: flash("Неверная ставка", "error"); return redirect(url_for("slots"))
    add_xp(p, bet); result = spin_slots(); win = 0
    if result[0] == result[1] == result[2]: win = bet * (50 if result[0] == "7️⃣" else (20 if result[0] == "💎" else 10))
    elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]: win = bet * 2
    if win > 0: p["balance"] += win
    else:
        p["balance"] -= bet; data["bank"] = data.get("bank", 0) + bet
    data["history"].append({"uid": session["uid"], "game": "slots", "bet": bet, "result": result, "win": win, "time": time.strftime("%H:%M")})
    save_data(data)
    return render_template("slots_result.html", player=p, result=result, win=win, bet=bet)

@app.route("/mines")
@login_required
def mines():
    data = load_data(); p = data["players"].get(session["uid"])
    if not p: return redirect(url_for("logout"))
    game = data.get("mines_games", {}).get(session["uid"], {"active": False, "bet": 0, "mines": 3, "bombs": [], "opened": [], "win": 0})
    return render_template("mines.html", player=p, game=game)

@app.route("/mines/start", methods=["POST"])
@login_required
def mines_start():
    data = load_data(); p = data["players"].get(session["uid"])
    if not p or p["banned"]: return redirect(url_for("mines"))
    try: bet, mines_count = int(request.form.get("bet", 0)), int(request.form.get("mines", 3))
    except: return redirect(url_for("mines"))
    if bet <= 0 or bet > p["balance"]: flash("Неверная ставка", "error"); return redirect(url_for("mines"))
    add_xp(p, bet); p["balance"] -= bet; data["bank"] = data.get("bank", 0) + bet
    if "mines_games" not in data: data["mines_games"] = {}
    data["mines_games"][session["uid"]] = create_mines_game(session["uid"], bet, mines_count)
    save_data(data); return redirect(url_for("mines"))

@app.route("/mines/open", methods=["POST"])
@login_required
def mines_open():
    data = load_data(); p = data["players"].get(session["uid"])
    game = data.get("mines_games", {}).get(session["uid"])
    if not p or not game or not game.get("active"): return redirect(url_for("mines"))
    try: cell = int(request.form.get("cell", -1))
    except: return redirect(url_for("mines"))
    if cell in game["opened"]: return redirect(url_for("mines"))
    if cell in game["bombs"]:
        game["active"] = False; game["win"] = 0
        data["history"].append({"uid": session["uid"], "game": "mines", "bet": game["bet"], "result": "bomb", "win": 0, "time": time.strftime("%H:%M")})
        flash(f"💥 БУМ! Потеряно {game['bet']}", "error")
    else:
        game["opened"].append(cell)
        game["win"] = int(game["bet"] * (1.0 + (len(game["opened"]) * (25 / (25 - game["mines"]))) * 0.2))
        if len(game["opened"]) == (25 - game["mines"]):
            game["active"] = False; p["balance"] += game["win"]
            data["history"].append({"uid": session["uid"], "game": "mines", "bet": game["bet"], "result": "win", "win": game["win"], "time": time.strftime("%H:%M")})
            flash(f"🏆 Выигрыш: {game['win']}", "success")
    save_data(data); return redirect(url_for("mines"))

@app.route("/mines/cashout", methods=["POST"])
@login_required
def mines_cashout():
    data = load_data(); p = data["players"].get(session["uid"])
    game = data.get("mines_games", {}).get(session["uid"])
    if not p or not game or not game.get("active"): return redirect(url_for("mines"))
    if game["win"] > 0:
        p["balance"] += game["win"]
        data["history"].append({"uid": session["uid"], "game": "mines", "bet": game["bet"], "result": "cashout", "win": game["win"], "time": time.strftime("%H:%M")})
        flash(f"💰 Забрано {game['win']}", "success")
    else: flash("Нечего забирать", "error")
    game["active"] = False; save_data(data); return redirect(url_for("mines"))

# --- БОНУСЫ И ПРОМО ---
@app.route("/daily_bonus", methods=["POST"])
@login_required
def daily_bonus():
    data = load_data(); p = data["players"].get(session["uid"])
    if not p: return redirect(url_for("logout"))
    if (time.time() - p.get("last_daily_bonus", 0)) < 86400: flash("Бонус уже получен!", "error")
    else:
        bonus = random.choice([500, 1000, 1500, 2000, 3000, 5000])
        p["bank_balance"] = p.get("bank_balance", 0) + bonus
        p["last_daily_bonus"] = time.time(); save_data(data)
        flash(f"🎁 Бонус получен: {bonus} в Банк!", "success")
    return redirect(url_for("player"))

@app.route("/promo", methods=["POST"])
@login_required
def activate_promo():
    data = load_data(); p = data["players"].get(session["uid"])
    code = request.form.get("code", "").strip().upper()
    if code in data.get("promos", {}):
        promo = data["promos"][code]
        if not promo.get("used"):
            p["bank_balance"] += promo["amount"]; promo["used"] = True; save_data(data)
            flash(f"🎁 Промокод активирован: +{promo['amount']}!", "success")
        else: flash("Промокод уже использован.", "error")
    else: flash("Неверный промокод.", "error")
    return redirect(url_for("player"))

@app.route("/admin")
@admin_required
def admin():
    return render_template("admin.html", data=load_data())

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)