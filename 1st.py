from flask import Flask, render_template, request, redirect, session, flash, jsonify
from flask_mysqldb import MySQL
from passlib.hash import sha256_crypt
from datetime import date, timedelta

app = Flask(__name__)
app.secret_key = "your_secret_key"

# ---------------- MYSQL CONFIG ----------------
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''     # put your XAMPP root password here if any
app.config['MYSQL_DB'] = 'fittracker'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)

# ---------------- FUNCTIONS ----------------
def calculate_factor(weight, height, age, gender):
    if gender == 'male':
        return 10 * weight + 6.25 * height - 5 * age + 5
    else:
        return 10 * weight + 6.25 * height - 5 * age - 161

def calculate_maintenance_calories(factor, activity_level):
    factors = {
        'sedentary': 1.2,
        'light': 1.375,
        'moderate': 1.55,
        'active': 1.725,
        'very_active': 1.9
    }
    return factor * factors.get(activity_level, 1.2)

def get_diet_plan(maintenance_calories):
    protein = maintenance_calories * 0.3 / 4
    fat = maintenance_calories * 0.3 / 9
    carbs = maintenance_calories * 0.4 / 4
    return {
        'protein': f"{int(protein)} grams",
        'fat': f"{int(fat)} grams",
        'carbs': f"{int(carbs)} grams"
    }

# ---------------- ROUTES ----------------

@app.route('/')
def index():
    return render_template('index.html')

# Login page
@app.route('/login')
def login():
    return render_template('login.html')

# Signup page (GET shows form, POST registers)
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'GET':
        return render_template('signup.html')

    username = request.form['username']
    password = request.form['password']
    role = request.form.get('role', 'user')

    cur = mysql.connection.cursor()
    cur.execute("SELECT id FROM users WHERE username=%s", (username,))
    exists = cur.fetchone()
    if exists:
        flash("Username already exists!")
        cur.close()
        return redirect('/signup')

    hashed_password = sha256_crypt.hash(password)
    cur.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                (username, hashed_password, role))
    mysql.connection.commit()

    # get id
    cur.execute("SELECT id FROM users WHERE username=%s", (username,))
    user = cur.fetchone()
    cur.close()

    flash("Account created successfully! Please log in.")
    return redirect('/login')

# Login handler (form action should POST to /loginkr)
@app.route('/loginkr', methods=['POST'])
def loginkr():
    username = request.form['username']
    password = request.form['password']
    role = request.form.get('role')

    cur = mysql.connection.cursor()
    if role:
        cur.execute("SELECT id, password, role FROM users WHERE username=%s AND role=%s", (username, role))
    else:
        cur.execute("SELECT id, password, role FROM users WHERE username=%s", (username,))
    user = cur.fetchone()
    cur.close()

    if not user:
        flash("User not found or wrong role!")
        return redirect('/login')

    stored_hash = user['password']
    if stored_hash is None:
        flash("No password set for this user (DB issue).")
        return redirect('/login')

    try:
        if sha256_crypt.verify(password, stored_hash):
            session['username'] = username
            session['user_id'] = user['id']
            session['role'] = user['role']
            if user['role'] == "admin":
                return redirect('/admin')
            return redirect('/user')
        else:
            flash("Incorrect password!")
            return redirect('/login')
    except Exception:
        flash("Authentication error!")
        return redirect('/login')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# ---------------- DASHBOARDS ----------------
@app.route('/admin')
def admin_dashboard():
    if 'username' in session and session.get('role') == "admin":
        return render_template('afterlogin.html')  # or a custom admin page
    return redirect('/login')

@app.route('/user')
def user_dashboard():
    if 'username' not in session:
        return redirect('/login')

    user_id = session.get('user_id')
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT id, challenge_name, start_date, end_date, progress, reward_unlocked, status
        FROM challenge_enrollments
        WHERE user_id=%s
        ORDER BY id DESC
        LIMIT 1
    """, (user_id,))
    challenge = cur.fetchone()
    cur.close()

    return render_template('userlogin.html', challenge=challenge)

# ---------------- CHALLENGE API ROUTES ----------------
@app.route('/enroll_challenge', methods=['POST'])
def enroll_challenge():
    if 'username' not in session:
        return jsonify({"message": "Please login first."}), 401

    data = request.get_json()
    if not data or 'challenge_name' not in data:
        return jsonify({"message": "Invalid request."}), 400

    challenge_name = data['challenge_name']
    user_id = session.get('user_id')

    cur = mysql.connection.cursor()
    cur.execute("SELECT id FROM challenge_enrollments WHERE user_id=%s AND challenge_name=%s",
                (user_id, challenge_name))
    if cur.fetchone():
        cur.close()
        return jsonify({"message": "You are already enrolled in this challenge."})

    # Decide duration & reward
    if "7-Day" in challenge_name or "7 Day" in challenge_name:
        duration_days = 7
        reward = "Whey Protein Pack"
    elif "30-Day" in challenge_name or "30 Day" in challenge_name:
        duration_days = 30
        reward = "Creatine Supplement"
    else:
        duration_days = 7
        reward = "Gym Subscription"

    start = date.today()
    end = start + timedelta(days=duration_days)

    cur.execute("""
        INSERT INTO challenge_enrollments
        (user_id, challenge_name, status, start_date, end_date, progress, reward_unlocked)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (user_id, challenge_name, 'in_progress', start, end, 0, reward))

    mysql.connection.commit()
    cur.close()

    return jsonify({"message": f"Enrolled in {challenge_name} successfully!"})

@app.route('/update_progress', methods=['POST'])
def update_progress():
    if 'username' not in session:
        flash("Please login first.")
        return redirect('/login')

    user_id = session.get('user_id')
    challenge_name = request.form.get('challenge_name')
    try:
        progress = int(request.form.get('progress', 0))
    except ValueError:
        progress = 0

    progress = max(0, min(100, progress))
    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE challenge_enrollments
        SET progress=%s, status=%s
        WHERE user_id=%s AND challenge_name=%s
    """, (progress, 'completed' if progress >= 100 else 'in_progress', user_id, challenge_name))
    mysql.connection.commit()
    cur.close()
    flash("Progress updated.")
    return redirect('/user')

@app.route('/complete_challenge', methods=['POST'])
def complete_challenge():
    if 'username' not in session:
        flash("Please login first.")
        return redirect('/login')

    user_id = session.get('user_id')
    challenge_name = request.form.get('challenge_name')
    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE challenge_enrollments
        SET status=%s, end_date=%s, progress=%s
        WHERE user_id=%s AND challenge_name=%s
    """, ('completed', date.today(), 100, user_id, challenge_name))
    mysql.connection.commit()
    cur.close()
    flash("Challenge marked as completed. Reward unlocked!")
    return redirect('/user')

# ---------------- DIET ----------------
@app.route('/diet', methods=['GET', 'POST'])
def diet():
    if request.method == 'POST':
        weight = float(request.form['weight'])
        height = float(request.form['height'])
        age = int(request.form['age'])
        gender = request.form['gender']
        activity_level = request.form['activity_level']

        factor = calculate_factor(weight, height, age, gender)
        maintenance_calories = calculate_maintenance_calories(factor, activity_level)
        diet_plan = get_diet_plan(maintenance_calories)

        return render_template('diet.html',
                               maintenance_calories=maintenance_calories,
                               diet_plan=diet_plan)
    return render_template('diet.html')

# ---------------- OTHER PAGES ----------------
@app.route('/feedback')
def feedback():
    return render_template('feedback.html')

@app.route('/contact')
def contact():
    return render_template('contactus.html')

@app.route('/afterlogin')
def afterlogin():
    return render_template('afterlogin.html')

if __name__ == "__main__":
    app.run(debug=True)
