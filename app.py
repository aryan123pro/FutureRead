from flask import Flask, render_template, request, redirect, flash, session, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from cs50 import SQL
from dotenv import load_dotenv
import openai
import base64
import os
from openai import OpenAI
import psycopg2
from psycopg2.extras import RealDictCursor

# PostgreSQL database connection
def get_db():
    return psycopg2.connect(os.getenv("DATABASE_URL"), cursor_factory=RealDictCursor)


def query_db(query, args=(), one=False):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(query, args)
    results = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()
    return (results[0] if results else None) if one else results

def execute_db(query, args=()):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(query, args)
    conn.commit()
    cur.close()
    conn.close()



# Load environment variables
load_dotenv()



# Initialize Flask app
app = Flask(__name__)
app.secret_key = "dev"  # Change this in production

# Configure Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Set OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

# Flask-Mail config
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False

mail = Mail(app)
s = URLSafeTimedSerializer(app.secret_key)

# User class
class User(UserMixin):
    def __init__(self, id, username, email, avatar=None):
        self.id = id
        self.username = username
        self.email = email
        self.avatar = avatar


@login_manager.user_loader
def load_user(user_id):
    user = query_db("SELECT * FROM users WHERE id = %s", (user_id,), one=True)
    if user:
        return User(user["id"], user["username"], user["email"], user.get("avatar"))
    return None



#url config
@app.context_processor
def inject_avatar():
    if current_user.is_authenticated:
        if hasattr(current_user, "avatar") and current_user.avatar:
            avatar_url = url_for("static", filename=f"avatars/{current_user.avatar}")
        else:
            avatar_url = url_for("static", filename="avatars/default.png")
        return dict(avatar_url=avatar_url)
    return dict(avatar_url=None)


# -------------------- Routes --------------------

@app.route("/")
def home():
    avatar_url = None
    if current_user.is_authenticated:
        user = query_db("SELECT avatar FROM users WHERE id = %s", (current_user.id,), one=True)
        if user and user["avatar"]:
            avatar_url = url_for("static", filename=f"avatars/{user['avatar']}")
    return render_template("index.html", now=datetime.now())


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        try:
            username = request.form.get("username")
            email = request.form.get("email")
            password = request.form.get("password")
            dob = request.form.get("dob")
            birth_time = request.form.get("birth_time")
            birth_place = request.form.get("birth_place")
            gender = request.form.get("gender")

            if not (username and email and password):
                flash("All fields are required.")
                return redirect("/signup")

            existing = query_db("SELECT * FROM users WHERE email = %s", (email,))
            if existing:
                flash("Email already exists.")
                return redirect("/signup")

            password_hash = generate_password_hash(password)

            execute_db(
                "INSERT INTO users (username, email, password_hash, dob, birth_time, birth_place, gender, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (username, email, password_hash, dob, birth_time, birth_place, gender, datetime.utcnow())
            )

            flash("Account created successfully!")
            return redirect("/login")

        except Exception as e:
            flash(f"Error: {e}")
            return redirect("/signup")

    return render_template("signup.html")



@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = query_db("SELECT * FROM users WHERE email = %s", (email,), one=True)
        if not user:
            flash("Email not found.")
            return redirect("/login")

        if not check_password_hash(user["password_hash"], password):
            flash("Incorrect password.")
            return redirect("/login")

        # Create a User object and log in using flask_login
        user_obj = User(user["id"], user["username"], user["email"])
        login_user(user_obj)

        flash("Login successful!")
        return redirect("/")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.")
    return redirect("/")


@app.route("/palm", methods=["GET", "POST"])
@login_required
def palmreader():
    reading = None
    image_url = None

    if request.method == "POST":
        image = request.files["palm_image"]
        if image:
            path = f"static/palm/{image.filename}"
            os.makedirs("static/palm", exist_ok=True)
            image.save(path)
            image_url = path

            with open(path, "rb") as img_file:
                encoded_string = base64.b64encode(img_file.read()).decode("utf-8")

            prompt = (
                "You are a mystical palm reader. Based on this user's palm image, "
                "generate a magical, wise, and inspiring palm reading as if you saw the following image:"
                "\n\n[This is an image of a palm. Use your mystical powers to give an interpretation. Answer in bullet points by explaining each and everthing also BE STRAIGHTFOWRWARD with you answer and focus on user understandabiliy]"
                "Be Honest and tell everything the truth though if it is negative and mention accuracy of the reading at last also please try keeping it above 70%."
            )

            try:
                client = OpenAI()  # Picks up OPENAI_API_KEY from .env or system env
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a mystical palm reader."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.8
                )
                reading = response.choices[0].message.content
            except Exception as e:
                reading = f"⚠️ Error fetching reading: {e}"

    return render_template("palm.html", reading=reading, image_url=image_url)

@app.route("/oracle", methods=["GET", "POST"])
@login_required
def oracle():
    
    if "oracle_chat" not in session:
        session["oracle_chat"] = []

    if request.method == "POST":
        # Accept message from either JSON (JS fetch) or form (HTML form)
        message = request.get_json()["message"] if request.is_json else request.form.get("message")

        if message:
            # Add user's message
            session["oracle_chat"].append({"role": "user", "content": message})

            try:
                client = OpenAI()

                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",  # Use "gpt-3.5-turbo" if needed
                    messages=[
                        {"role": "system", "content": "You are the Oracle — a mystical, all-knowing ancient spirit. Reply with wisdom, mystery, and spiritual metaphors. BE STRAIGHTFOWRWARD with you answer and focus on user understandabiliy dont give so diplomatic answers, ask for more information to interpret if the user asks something and you dont have sufficient information about the user" }
                    ] + session["oracle_chat"],
                    temperature=0.9
                )

                oracle_reply = response.choices[0].message.content
                session["oracle_chat"].append({"role": "assistant", "content": oracle_reply})

            except Exception as e:
                flash(f"Oracle error: {e}", "danger")

    return render_template("oracle.html", chat=session["oracle_chat"])


@app.route("/oracle/clear")
@login_required
def clear_oracle():
    session.pop("oracle_chat", None)
    flash("Oracle chat has been cleared.")
    return redirect("/oracle")

@app.route("/astrology")
@login_required
def astrology():
    user_id = current_user.id

    user = query_db(
        "SELECT dob, birth_time, birth_place, astrology_reading, astrology_timestamp FROM users WHERE id = %s",
        (user_id,),
        one=True
    )

    if not user or not user["dob"]:
        flash("Your birth details are incomplete. Please update your profile.", "warning")
        return redirect("/profile")

    now = datetime.utcnow()

    if user["astrology_reading"] and user["astrology_timestamp"]:
        last_time = datetime.fromisoformat(user["astrology_timestamp"])
        if now.date() == last_time.date():
            return render_template(
                "astrology.html",
                reading=user["astrology_reading"],
                dob=user["dob"],
                time=user["birth_time"],
                place=user["birth_place"]
            )

    # 🔮 Generate new reading
    prompt = (
        f"You are a wise astrologer. Based on the user's birth date: {user['dob']}, "
        f"time: {user['birth_time']}, and place: {user['birth_place']}, provide a spiritual astrology reading. Kundali which we call in india"
        f"Be Honest and tell everything the truth though if it is negative and mention accuracy of the reading at last also please try keeping it above 70%. Please make it in marathi language"
    )

    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a mystical astrologer who gives magical, empowering daily readings."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.85
        )
        reading = response.choices[0].message.content

        # 💾 Save to PostgreSQL
        execute_db(
            "UPDATE users SET astrology_reading = %s, astrology_timestamp = %s WHERE id = %s",
            (reading, now.isoformat(), user_id)
        )

        return render_template(
            "astrology.html",
            reading=reading,
            dob=user["dob"],
            time=user["birth_time"],
            place=user["birth_place"]
        )
    except Exception as e:
        flash(f"Error: {e}", "danger")
        return redirect("/")



@app.route("/oracle/stream", methods=["POST"])
@login_required
def oracle_stream():
    user_msg = request.json.get("prompt")

    # 🎯 Fetch user details from PostgreSQL
    user = query_db(
        "SELECT username, dob, birth_time, birth_place, gender, language FROM users WHERE id = %s",
        (current_user.id,),
        one=True
    )

    if not user:
        return "User info not found", 400

    # 💫 Extract values
    name = user["username"]
    dob = user["dob"]
    time = user["birth_time"]
    place = user["birth_place"]
    gender = user["gender"]
    language = user["language"]

    # 🧙 Mystical system prompt with full context
    system_prompt = f"""
    You are the divine Oracle of FutureRead. You are speaking to a seeker named {name}, 
    who was born on {dob} at {time} in {place}. They identify as {gender}, and their preferred language is {language}.
    Use this information to craft insightful, poetic, and cosmic responses. Be mysterious and wise. But also be sensible and still straightforward. So the User Understands. 
    Always guide them gently with personalized, spiritual insights.
    Answer in very less time.
    """

    def generate():
        client = OpenAI()
        stream = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg}
            ],
            stream=True
        )
        for chunk in stream:
            if chunk.choices[0].delta.get("content"):
                yield f"data: {chunk.choices[0].delta['content']}\n\n"

    return Response(generate(), mimetype="text/event-stream")


@app.route("/tarot")
@login_required
def tarot():
    import random
    from datetime import datetime

    user_id = current_user.id

    user = query_db(
        "SELECT tarot_cards, tarot_timestamp FROM users WHERE id = %s",
        (user_id,),
        one=True
    )

    now = datetime.utcnow()

    tarot_cards = user["tarot_cards"] if user and user["tarot_cards"] else None
    tarot_time = user["tarot_timestamp"] if user and user["tarot_timestamp"] else None

    if tarot_cards and tarot_time:
        try:
            # PostgreSQL may return datetime or string
            if isinstance(tarot_time, str):
                tarot_time = datetime.fromisoformat(tarot_time)
            delta = now - tarot_time
            if delta.days < 1:
                cards = tarot_cards.split(",")
                return render_template("tarot.html", cards=cards)
        except Exception as e:
            print(f"⚠️ Failed to parse tarot_timestamp: {e}")

    # Draw new tarot cards
    all_cards = os.listdir("static/cards")
    deck = [c for c in all_cards if c.endswith(".png") and "back" not in c and "border" not in c]
    selected = random.sample(deck, 3)

    execute_db(
        "UPDATE users SET tarot_cards = %s, tarot_timestamp = %s WHERE id = %s",
        (",".join(selected), now.isoformat(), user_id)
    )

    return render_template("tarot.html", cards=selected)

@app.route("/tarot_reading", methods=["POST"])
@login_required
def tarot_reading():
    from flask import jsonify, request
    data = request.get_json()
    cards = data.get("cards", [])

    if not cards or len(cards) != 3:
        return jsonify({"reading": "Please draw exactly 3 cards to receive a proper reading."})

    card_names = [c.replace("_", " ").replace(".png", "") for c in cards]

    prompt = f"""
You are a wise and mystical Tarot oracle. Interpret these three cards drawn in a past-present-future spread:

1. {card_names[0]}
2. {card_names[1]}
3. {card_names[2]}

Give a magical and insightful interpretation.
Be Honest and tell everything the truth though if it is negative and mention accuracy of the reading at last also please try keeping it above 70%.
"""

    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a wise Tarot oracle who gives magical readings. "
                        "Answer always in bullet points by saying what each card means so the user understands. "
                        "At the end, give an overview in oracle-style but simple, human-understandable language."
                        "Be Honest and tell everything the truth though if it is negative and mention accuracy of the reading at last also please try keeping it above 70%."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.85
        )
        reading = response.choices[0].message.content
        return jsonify({"reading": reading.strip()})

    except Exception as e:
        return jsonify({"reading": f"Open all the cards to see your fate ✨ (error: {e})"})


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user_id = current_user.id

    # Fetch current user details
    user = query_db("SELECT * FROM users WHERE id = %s", (user_id,), one=True)

    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        dob = request.form.get("dob")
        birth_time = request.form.get("birth_time")
        birth_place = request.form.get("birth_place")
        gender = request.form.get("gender")

        # Handle avatar upload
        avatar = request.files.get("avatar")
        avatar_filename = user.get("avatar") or "default.png"
        if avatar and avatar.filename:
            os.makedirs("static/avatars", exist_ok=True)
            avatar_filename = f"user_{user_id}.png"
            avatar.save(os.path.join("static/avatars", avatar_filename))

        # Update the user record
        execute_db("""
            UPDATE users
            SET username = %s, email = %s, dob = %s, birth_time = %s,
                birth_place = %s, gender = %s, avatar = %s
            WHERE id = %s
        """, (username, email, dob, birth_time, birth_place, gender, avatar_filename, user_id))

        flash("Profile updated successfully.")
        return redirect("/profile")

    return render_template("profile.html", user=user)


# Route to show 'forgot password' form
@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        email = request.form.get("email")
        token = s.dumps(email, salt='reset-password')
        reset_link = url_for("reset_password", token=token, _external=True)

        msg = Message(
            subject="🪄 FutureRead Password Reset",
            sender=app.config["MAIL_USERNAME"],
            recipients=[email]
        )
        msg.body = f"""
        Hello,

        You requested a password reset for your FutureRead account.
        Click the link below to reset your password:

        {reset_link}

        If you didn't request this, ignore this email.

        ✨ - FutureRead
        """
        mail.send(msg)
        flash("Reset email sent! Check your inbox.")
        return redirect("/login")

    return render_template("forgot.html")

@app.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        email = s.loads(token, salt='reset-password', max_age=3600)
    except:
        flash("The reset link is invalid or has expired.")
        return redirect("/forgot")

    if request.method == "POST":
        new_password = request.form.get("password")
        hashed = generate_password_hash(new_password)

        # ✅ Update password in PostgreSQL
        execute_db("UPDATE users SET password_hash = %s WHERE email = %s", (hashed, email))

        flash("✅ Password updated! You can now login.")
        return redirect("/login")

    return render_template("reset_password.html", token=token)


from openai import OpenAI
client = OpenAI()

@app.route("/daily")
@login_required
def zodiac_daily():
    user = query_db("SELECT dob FROM users WHERE id = %s", (current_user.id,), one=True)

    if not user or not user["dob"]:
        flash("Please update your birth date in your profile.")
        return redirect("/profile")

    dob = user["dob"]
    zodiac = get_zodiac_sign(dob)

    prompt = (
        f"Give today's poetic and mystical horoscope for someone with the zodiac sign {zodiac}. "
        "Make it warm and spiritual. Give Response as fast as possible so user doesn't need to wait for a long time."
        "Be Honest and tell everything the truth though if it is negative."
    )

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a mystical astrologer who gives magical, empowering daily readings."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.85,
    )

    reading = response.choices[0].message.content.strip()

    return render_template("daily.html", zodiac=zodiac, reading=reading)

from datetime import datetime

def get_zodiac_sign(dob_str):
    if isinstance(dob_str, str):
        dob = datetime.strptime(dob_str, "%Y-%m-%d")
    else:
        dob = dob_str  # already a datetime.date

    day = dob.day
    month = dob.month
    signs = [
        ("Capricorn", 20), ("Aquarius", 19), ("Pisces", 20),
        ("Aries", 20), ("Taurus", 21), ("Gemini", 21),
        ("Cancer", 23), ("Leo", 23), ("Virgo", 23),
        ("Libra", 23), ("Scorpio", 23), ("Sagittarius", 22), ("Capricorn", 31)
    ]
    if day < signs[month - 1][1]:
        return signs[month - 1][0]
    else:
        return signs[month][0]

if __name__ == '__main__':
    app.run(debug=True)
