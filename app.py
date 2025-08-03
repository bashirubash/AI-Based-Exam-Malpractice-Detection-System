from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import os
import face_recognition
import cv2
import numpy as np
import base64
from datetime import datetime
from PIL import Image

app = Flask(__name__)
app.secret_key = 'exam_ai_system_secret_key'

DATABASE = 'exam_ai_system.db'

# --- Utility Functions ---
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def encode_face(image_path):
    image = face_recognition.load_image_file(image_path)
    encodings = face_recognition.face_encodings(image)
    return encodings[0] if encodings else None

def decode_image(data_url):
    encoded = data_url.split(',')[1]
    binary_data = base64.b64decode(encoded)
    img = Image.open(io.BytesIO(binary_data))
    return np.array(img)

def insert_alert(student_id, name, activity):
    conn = get_db()
    c = conn.cursor()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("INSERT INTO alerts (student_id, name, activity, timestamp) VALUES (?, ?, ?, ?)",
              (student_id, name, activity, timestamp))
    conn.commit()
    conn.close()

# --- Routes ---
@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password))
    user = cursor.fetchone()
    conn.close()

    if user:
        session['username'] = user['username']
        session['role'] = user['role']
        if user['role'] == 'exam_officer':
            return redirect(url_for('register_student'))
        elif user['role'] == 'invigilator':
            return redirect(url_for('verify_student'))
        elif user['role'] == 'admin':
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid role', 'danger')
    else:
        flash('Invalid username or password', 'danger')
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/register_student', methods=['GET', 'POST'])
def register_student():
    if session.get('role') != 'exam_officer':
        return redirect(url_for('index'))

    if request.method == 'POST':
        student_id = request.form['student_id']
        name = request.form['name']
        level = request.form['level']
        file = request.files['photo']

        if file:
            filepath = f'static/uploads/{student_id}.jpg'
            file.save(filepath)
            encoding = encode_face(filepath)
            if encoding is not None:
                encoding_blob = sqlite3.Binary(np.array(encoding).tobytes())
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO students (student_id, name, level, face_encoding) 
                    VALUES (?, ?, ?, ?)
                """, (student_id, name, level, encoding_blob))
                conn.commit()
                conn.close()
                flash('Student registered successfully', 'success')
            else:
                flash('Face encoding failed. Use a clearer image.', 'danger')

    return render_template('register_student.html')

@app.route('/verify_student', methods=['GET', 'POST'])
def verify_student():
    if session.get('role') != 'invigilator':
        return redirect(url_for('index'))

    if request.method == 'POST':
        image_data = request.form['image_data']
        np_image = decode_image(image_data)
        encoding = face_recognition.face_encodings(np_image)
        if not encoding:
            flash('No face found', 'danger')
            return redirect(url_for('verify_student'))
        encoding = encoding[0]

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT student_id, name, level, face_encoding FROM students")
        students = cursor.fetchall()
        for student in students:
            stored_encoding = np.frombuffer(student['face_encoding'], dtype=np.float64)
            match = face_recognition.compare_faces([stored_encoding], encoding)[0]
            if match:
                flash(f"Match found: ID {student['student_id']}, Name {student['name']}, Level {student['level']}", 'success')
                return render_template("malpractice_monitor.html", student=student)
        flash("No matching student found", 'danger')
        insert_alert("Unknown", "Unknown", "Face mismatch / unauthorized student")
        return redirect(url_for('verify_student'))

    return render_template('verify_student.html')

@app.route('/create_invigilator', methods=['GET', 'POST'])
def create_invigilator():
    if session.get('role') != 'admin':
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']

        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                           (username, password, role))
            conn.commit()
            flash("User created successfully", "success")
        except sqlite3.IntegrityError:
            flash("Username already exists.", "danger")
        conn.close()
        return redirect(url_for("create_invigilator"))

    return render_template("add_user.html")

@app.route('/dashboard')
def dashboard():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM students")
    student_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM users WHERE role='invigilator'")
    invigilator_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM alerts")
    alert_count = c.fetchone()[0]

    c.execute("SELECT student_id, name, activity, timestamp FROM alerts ORDER BY timestamp DESC LIMIT 10")
    alerts = [
        {'student_id': row[0], 'name': row[1], 'activity': row[2], 'timestamp': row[3]}
        for row in c.fetchall()
    ]
    conn.close()

    return render_template("dashboard.html", student_count=student_count,
                           invigilator_count=invigilator_count,
                           alert_count=alert_count, alerts=alerts)

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT CHECK(role IN ('admin', 'exam_officer', 'invigilator'))
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            name TEXT,
            level TEXT,
            face_encoding BLOB
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            name TEXT,
            activity TEXT,
            timestamp TEXT
        )
    ''')
    c.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES ('admin', 'admin123', 'admin')")
    c.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES ('officer', '1234', 'exam_officer')")
    c.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES ('invigilator', '1234', 'invigilator')")

    conn.commit()
    conn.close()

init_db()

if __name__ == "__main__":
    app.run(debug=True)
