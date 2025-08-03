import os
import cv2
import sqlite3
import face_recognition
import numpy as np
import speech_recognition as sr
from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Inject current year
@app.context_processor
def inject_now():
    return {'now': datetime.now}

DB_PATH = 'exam_ai_system.db'
UPLOAD_FOLDER = 'static/snapshots'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
    user = cur.fetchone()

    if user:
        session['username'] = user['username']
        session['role'] = user['role']
        if user['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif user['role'] == 'exam_officer':
            return redirect(url_for('exam_officer_dashboard'))
        else:
            return redirect(url_for('invigilator_dashboard'))
    else:
        flash("Invalid credentials", "danger")
        return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out", "info")
    return redirect(url_for('index'))

@app.route('/admin')
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    return render_template('admin_dashboard.html')
@app.route('/exam_officer')
def exam_officer_dashboard():
    if session.get('role') != 'exam_officer':
        return redirect(url_for('index'))
    return render_template('exam_officer_dashboard.html')

@app.route('/invigilator')
def invigilator_dashboard():
    if session.get('role') != 'invigilator':
        return redirect(url_for('index'))
    return render_template('invigilator_dashboard.html')

@app.route('/register_student', methods=['GET', 'POST'])
def register_student():
    if session.get('role') != 'exam_officer':
        return redirect(url_for('index'))

    if request.method == 'POST':
        student_id = request.form['student_id']
        name = request.form['name']
        level = request.form['level']
        image = request.files['image']

        filename = secure_filename(f'{student_id}_{datetime.now().strftime("%Y%m%d%H%M%S")}.jpg')
        path = os.path.join(UPLOAD_FOLDER, filename)
        image.save(path)

        # Load and encode image
        img = face_recognition.load_image_file(path)
        encodings = face_recognition.face_encodings(img)

        if len(encodings) > 0:
            encoding = encodings[0]
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO students (student_id, name, level, face_encoding) VALUES (?, ?, ?, ?)",
                           (student_id, name, level, encoding.tobytes()))
            conn.commit()
            conn.close()
            flash("Student registered successfully", "success")
        else:
            os.remove(path)
            flash("Face not detected. Please try again.", "danger")
        return redirect(url_for('register_student'))

    return render_template('register_student.html')
@app.route('/verify_student', methods=['GET', 'POST'])
def verify_student():
    if session.get('role') != 'invigilator':
        return redirect(url_for('index'))

    student_data = None
    if request.method == 'POST':
        image = request.files['image']
        temp_path = os.path.join(UPLOAD_FOLDER, "temp.jpg")
        image.save(temp_path)

        unknown_img = face_recognition.load_image_file(temp_path)
        unknown_encodings = face_recognition.face_encodings(unknown_img)

        if len(unknown_encodings) > 0:
            unknown_encoding = unknown_encodings[0]

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM students")
            students = cursor.fetchall()

            for student in students:
                known_encoding = np.frombuffer(student['face_encoding'], dtype=np.float64)
                match = face_recognition.compare_faces([known_encoding], unknown_encoding)[0]
                if match:
                    student_data = {
                        "student_id": student["student_id"],
                        "name": student["name"],
                        "level": student["level"]
                    }
                    break
        else:
            flash("No face detected in uploaded image.", "danger")

    return render_template("verify_student.html", student=student_data)

@app.route('/start_exam', methods=['POST'])
def start_exam():
    if session.get('role') != 'invigilator':
        return redirect(url_for('index'))

    def detect_audio():
        recognizer = sr.Recognizer()
        mic = sr.Microphone()
        with mic as source:
            print("Listening for speech...")
            audio = recognizer.listen(source, phrase_time_limit=5)
            try:
                text = recognizer.recognize_google(audio)
                if text:
                    print("Audio detected:", text)
                    return "Speech detected!"
            except sr.UnknownValueError:
                pass
        return None

    def detect_eye_movement():
        # Simulated movement detection
        print("Tracking eye movement...")
        # In real app, integrate with webcam + dlib/mediapipe
        return "Suspicious movement!"

    alerts = []
    speech = detect_audio()
    if speech:
        alerts.append(speech)

    movement = detect_eye_movement()
    if movement:
        alerts.append(movement)

    if alerts:
        flash("Malpractice Detected: " + ", ".join(alerts), "danger")
    else:
        flash("Monitoring OK. No malpractice detected.", "success")

    return redirect(url_for("invigilator_dashboard"))
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

def init_db():
    conn = get_db()
    c = conn.cursor()

    # Create tables
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
    # Insert admin and default users
    c.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES ('admin', 'admin123', 'admin')")
    c.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES ('officer', '1234', 'exam_officer')")
    c.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES ('invigilator', '1234', 'invigilator')")

    conn.commit()
    conn.close()

# Initialize DB on first run
init_db()

# Run server
if __name__ == "__main__":
    app.run(debug=True)
