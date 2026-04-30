import os
import random
import re
import requests
import smtplib
import hashlib
from html import escape
from datetime import datetime, timedelta
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from dotenv import load_dotenv

try:
    from .models import BankingSystem
except ImportError:
    from models import BankingSystem

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

# Try multiple env var names for compatibility
BREVO_API_KEY = (
    os.getenv('BREVO_API_KEY')
    or os.getenv('BREVO_KEY')
)

if not BREVO_API_KEY:
    import sys
    print('WARNING: BREVO_API_KEY not found in environment variables. Email sending will fail.', file=sys.stderr)


def is_valid_email(email):
    return bool(email and re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email))

SMTP_SERVER = (
    os.getenv('SMTP_SERVER')
    or os.getenv('SMTP Server')
)
SMTP_PORT = int(os.getenv('SMTP_PORT') or os.getenv('Port') or 587)
SMTP_LOGIN = (
    os.getenv('SMTP_LOGIN')
    or os.getenv('Login')
)
SMTP_KEY = (
    os.getenv('SMTP_KEY')
    or os.getenv('SMTP key')
)
raw_brevo_sender_email = (
    os.getenv('BREVO_SENDER_EMAIL')
    or os.getenv('SYSTEM_APP')
    or os.getenv('System app')
)
BREVO_SENDER_EMAIL = raw_brevo_sender_email if is_valid_email(raw_brevo_sender_email) else 'no-reply@pevbanking.com'
if raw_brevo_sender_email and not is_valid_email(raw_brevo_sender_email):
    import sys
    print(f'WARNING: Invalid BREVO_SENDER_EMAIL value "{raw_brevo_sender_email}". Falling back to {BREVO_SENDER_EMAIL}.', file=sys.stderr)
BREVO_SENDER_NAME = os.getenv('BREVO_SENDER_NAME', 'PEV Banking')
BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'
ADMIN_CONTACT_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@pevbanking.com')

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY') or os.getenv('SUPABASE_KEY')
SUPABASE_SERVICE_ROLE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
SUPABASE_AUTH_KEY = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
SUPABASE_USERS_TABLE = os.getenv('SUPABASE_USERS_TABLE', 'app_users')
SUPABASE_ACCOUNTS_TABLE = os.getenv('SUPABASE_ACCOUNTS_TABLE', 'accounts')

app = Flask(__name__, template_folder=str(BASE_DIR / 'templates'))
app.secret_key = 'pev-banking-secret-key-2024'

# Disable caching for templates to ensure latest version is always served
@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

banking_system = BankingSystem()


def send_brevo_email(to_email, subject, html_content, text_content=None):
    if not text_content:
        text_content = re.sub('<[^<]+?>', '', html_content)

    if BREVO_API_KEY:
        if not is_valid_email(BREVO_SENDER_EMAIL):
            return False, 'Email sender address is invalid. Please configure BREVO_SENDER_EMAIL correctly.'
        payload = {
            'sender': {'name': BREVO_SENDER_NAME, 'email': BREVO_SENDER_EMAIL},
            'to': [{'email': to_email}],
            'subject': subject,
            'htmlContent': html_content,
            'textContent': text_content
        }
        try:
            response = requests.post(
                BREVO_API_URL,
                headers={
                    'accept': 'application/json',
                    'content-type': 'application/json',
                    'api-key': BREVO_API_KEY
                },
                json=payload,
                timeout=15
            )
            if response.status_code in (200, 201, 202):
                return True, None
            app.logger.error('Brevo REST send failed: %s %s', response.status_code, response.text)
            if response.status_code == 401 and SMTP_SERVER and SMTP_LOGIN and SMTP_KEY:
                app.logger.warning('Falling back to SMTP relay because REST API key failed')
            else:
                return False, f'Brevo error {response.status_code}: {response.text}'
        except Exception as exc:
            app.logger.exception('Brevo REST send exception')
            if not (SMTP_SERVER and SMTP_LOGIN and SMTP_KEY):
                return False, str(exc)
            app.logger.warning('Falling back to SMTP relay because REST send raised an exception')

    if not (SMTP_SERVER and SMTP_LOGIN and SMTP_KEY):
        app.logger.error('Email service not configured for REST or SMTP')
        return False, 'Email service not configured.'

    message = MIMEMultipart('alternative')
    message['Subject'] = subject
    message['From'] = f'{BREVO_SENDER_NAME} <{BREVO_SENDER_EMAIL}>'
    message['To'] = to_email
    message.attach(MIMEText(text_content, 'plain'))
    message.attach(MIMEText(html_content, 'html'))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_LOGIN, SMTP_KEY)
            server.sendmail(BREVO_SENDER_EMAIL, [to_email], message.as_string())
        return True, None
    except Exception as exc:
        app.logger.exception('Brevo SMTP send exception')
        return False, str(exc)


def supabase_insert_user(user_data):
    if not SUPABASE_URL or not SUPABASE_AUTH_KEY:
        return False, 'Supabase not configured.'
    if not user_data.get('username') or not user_data.get('email') or not user_data.get('password_hash'):
        return False, 'Missing user data for Supabase.'

    base_url = SUPABASE_URL.rstrip('/')
    supabase_url = base_url + f'/rest/v1/{SUPABASE_USERS_TABLE}'
    headers = {
        'apikey': SUPABASE_AUTH_KEY,
        'Authorization': f'Bearer {SUPABASE_AUTH_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }
    payload = {
        'full_name': user_data.get('full_name'),
        'username': user_data.get('username'),
        'email': user_data.get('email'),
        'phone_number': user_data.get('phone_number'),
        'password_hash': user_data.get('password_hash'),
        'is_admin': user_data.get('is_admin', False)
    }
    try:
        response = requests.post(supabase_url, json=payload, headers=headers, timeout=15)
        if response.status_code in (200, 201, 202):
            created = response.json()[0] if response.text else {}
            user_id = created.get('id')
            if user_id:
                account_url = base_url + f'/rest/v1/{SUPABASE_ACCOUNTS_TABLE}'
                account_payload = {
                    'user_id': user_id,
                    'balance': float(user_data.get('balance', 0.0) or 0.0)
                }
                account_response = requests.post(
                    account_url,
                    json=account_payload,
                    headers={**headers, 'Prefer': 'return=minimal'},
                    timeout=15
                )
                if account_response.status_code not in (200, 201, 202):
                    return False, f'Supabase account insert failed {account_response.status_code}: {account_response.text}'
            return True, None
        return False, f'Supabase insert failed {response.status_code}: {response.text}'
    except Exception as exc:
        return False, str(exc)


def record_signup_to_supabase(user):
    user_data = {
        'full_name': user.full_name,
        'username': user.username,
        'email': user.email,
        'phone_number': user.phone_number,
        'password_hash': user.password_hash,
        'balance': user.account.balance,
        'is_admin': user.is_admin
    }
    success, error = supabase_insert_user(user_data)
    if not success:
        app.logger.warning('Supabase signup sync failed for %s: %s', user.username, error)
    else:
        app.logger.info('Supabase signup synced for %s', user.username)
    return success

def generate_otp():
    return ''.join(str(random.randint(0, 9)) for _ in range(6))


def validate_signup_data(data):
    full_name = data.get('full_name', '').strip()
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    phone_number = data.get('phone_number', '').strip()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')

    if not all([full_name, username, email, phone_number, password, confirm_password]):
        return False, 'All fields are required.'
    if '@' not in email or '.' not in email:
        return False, 'Enter a valid email address.'
    if password != confirm_password:
        return False, 'Passwords do not match.'
    if len(password) < 6:
        return False, 'Password must be at least 6 characters.'

    normalized_phone = banking_system.normalize_phone_number(phone_number)
    if not normalized_phone:
        return False, 'Enter a valid Philippine mobile number.'

    if banking_system.get_user_by_phone(normalized_phone):
        return False, 'Phone number already exists.'
    if username in banking_system.users:
        return False, 'Username already exists.'
    if banking_system.get_user_by_email(email):
        return False, 'Email already exists.'

    return True, {
        'full_name': full_name,
        'username': username,
        'email': email,
        'phone_number': normalized_phone,
        'password': password,
        'confirm_password': confirm_password
    }


def admin_required():
    if 'username' not in session:
        return False
    user = banking_system.get_current_user()
    return user and user.is_admin


@app.route('/api/signup/send-otp', methods=['POST'])
def api_signup_send_otp():
    data = request.json or {}
    valid, result = validate_signup_data(data)
    if not valid:
        return jsonify({'success': False, 'message': result}), 400

    otp = generate_otp()
    expiry = (datetime.utcnow() + timedelta(minutes=10)).timestamp()
    session['signup_otp'] = otp
    session['signup_otp_expires'] = expiry
    session['signup_payload'] = result

    subject = 'PEV Banking Verification Code'
    html = (
        f'<p>Hi {result["full_name"]},</p>'
        f'<p>Your PEV Banking verification code is <strong>{otp}</strong>.</p>'
        '<p>This code will expire in 10 minutes.</p>'
        '<p>If you did not request this, please ignore this email.</p>'
    )

    success, error = send_brevo_email(result['email'], subject, html)
    if not success:
        return jsonify({'success': False, 'message': error or 'Failed to send verification email.'}), 500

    return jsonify({'success': True})


@app.route('/api/signup/verify-otp', methods=['POST'])
def api_signup_verify_otp():
    data = request.json or {}
    otp = data.get('otp', '').strip()
    stored_otp = session.get('signup_otp')
    stored_expires = session.get('signup_otp_expires')
    payload = session.get('signup_payload')

    if not stored_otp or not stored_expires or not payload:
        return jsonify({'success': False, 'message': 'Verification session expired. Please restart signup.'}), 400
    if datetime.utcnow().timestamp() > stored_expires:
        return jsonify({'success': False, 'message': 'Verification code expired.'}), 400
    if otp != stored_otp:
        return jsonify({'success': False, 'message': 'Invalid verification code.'}), 400

    if not banking_system.register(
        payload['full_name'],
        payload['username'],
        payload['password'],
        payload['phone_number'],
        payload['email']
    ):
        return jsonify({'success': False, 'message': 'Could not create account. Please try again.'}), 400

    user = banking_system.get_user_by_username(payload['username'])
    if user:
        record_signup_to_supabase(user)

    session.pop('signup_otp', None)
    session.pop('signup_otp_expires', None)
    session.pop('signup_payload', None)

    welcome_subject = 'Welcome to PEV Banking'
    welcome_html = (
        f'<p>Hi {payload["full_name"]},</p>'
        '<p>Your PEV Banking account has been created successfully.</p>'
        '<p>You can now log in with your username and password.</p>'
        '<p>Thank you for joining PEV Banking.</p>'
    )
    send_brevo_email(payload['email'], welcome_subject, welcome_html)

    return jsonify({'success': True, 'redirect': url_for('login')})

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if banking_system.login(username, password):
            session['username'] = username
            user = banking_system.get_current_user()
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials', 'error')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        full_name = request.form['full_name']
        username = request.form['username']
        email = request.form.get('email', '').strip()
        phone_number = request.form['phone_number']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        normalized_phone = banking_system.normalize_phone_number(phone_number)

        if not all([full_name, username, email, phone_number, password, confirm_password]):
            flash('All fields are required', 'error')
            return render_template('signup.html')
        if '@' not in email or '.' not in email:
            flash('Enter a valid email address', 'error')
            return render_template('signup.html')
        if not normalized_phone:
            flash('Enter a valid Philippine mobile number', 'error')
            return render_template('signup.html')
        if banking_system.get_user_by_phone(normalized_phone):
            flash('Phone number already exists', 'error')
            return render_template('signup.html')
        if banking_system.get_user_by_email(email):
            flash('Email already exists', 'error')
            return render_template('signup.html')
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('signup.html')
        if len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
            return render_template('signup.html')
        if banking_system.register(full_name, username, password, normalized_phone, email):
            user = banking_system.get_user_by_username(username)
            if user:
                record_signup_to_supabase(user)
            flash('Account created successfully! Please login.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Username or phone number already exists', 'error')
    return render_template('signup.html')

def get_account_number(username):
    raw = str(int(hashlib.md5(username.encode()).hexdigest(), 16))[:12].zfill(12)
    return f"{raw[:4]} {raw[4:8]} {raw[8:]}"

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    user = banking_system.get_current_user()
    if not user:
        return redirect(url_for('login'))
    recent_transactions = user.account.transactions[-5:] if user.account.transactions else []
    return render_template('dashboard.html',
                           balance=user.account.balance,
                           savings_balance=user.account.savings_balance,
                           current_balance=user.account.current_balance,
                           transactions=recent_transactions,
                           full_name=user.full_name,
                           account_number=get_account_number(user.username),
                           phone_number=banking_system.format_phone_number(user.phone_number),
                           email=getattr(user, 'email', ''),
                           photo=getattr(user, 'photo', ''))

@app.route('/admin')
def admin_dashboard():
    if not admin_required():
        return redirect(url_for('login'))
    stats = banking_system.get_all_stats()
    return render_template('admin_dashboard.html', stats=stats)

# ── Admin API ──────────────────────────────────────────────────

@app.route('/admin/api/users', methods=['GET'])
def admin_api_users():
    if not admin_required():
        return jsonify({'success': False}), 403
    q = request.args.get('q', '').lower()
    users = [u for u in banking_system.users.values() if not u.is_admin]
    if q:
        users = [
            u for u in users
            if q in u.full_name.lower()
            or q in u.username.lower()
            or q in banking_system.format_phone_number(u.phone_number).lower()
            or q in banking_system.normalize_phone_number(u.phone_number)
        ]
    return jsonify({'success': True, 'users': [
        {'username': u.username, 'full_name': u.full_name,
         'phone_number': banking_system.format_phone_number(u.phone_number),
         'balance': u.account.balance,
         'txn_count': len(u.account.transactions),
         'account_number': get_account_number(u.username)}
        for u in users
    ]})

@app.route('/admin/api/users/<username>', methods=['DELETE'])
def admin_delete_user(username):
    if not admin_required():
        return jsonify({'success': False}), 403
    if username not in banking_system.users or banking_system.users[username].is_admin:
        return jsonify({'success': False, 'message': 'User not found'})
    del banking_system.users[username]
    banking_system._save_users()
    return jsonify({'success': True})

@app.route('/admin/api/users/<username>/balance', methods=['POST'])
def admin_adjust_balance(username):
    if not admin_required():
        return jsonify({'success': False}), 403
    if username not in banking_system.users:
        return jsonify({'success': False, 'message': 'User not found'})
    try:
        amount = float(request.json['amount'])
        action = request.json.get('action', 'set')
        user = banking_system.users[username]
        if action == 'set':
            user.account.balance = amount
        elif action == 'add':
            user.account.balance += amount
        banking_system._save_users()
        return jsonify({'success': True, 'balance': user.account.balance})
    except:
        return jsonify({'success': False, 'message': 'Invalid amount'})

@app.route('/admin/api/transactions', methods=['GET'])
def admin_api_transactions():
    if not admin_required():
        return jsonify({'success': False}), 403
    stats = banking_system.get_all_stats()
    txns = [{'id': i['txn'].id, 'user': i['user'],
              'type': i['txn'].type, 'amount': i['txn'].amount,
              'timestamp': i['txn'].timestamp,
              'recipient': i['txn'].recipient}
            for i in stats['all_transactions']]
    return jsonify({'success': True, 'transactions': txns})

@app.route('/admin/api/messages', methods=['GET'])
def admin_api_messages():
    if not admin_required():
        return jsonify({'success': False}), 403
    messages = banking_system.get_admin_messages()
    return jsonify({'success': True, 'messages': messages})

@app.route('/admin/api/messages/<message_id>/read', methods=['POST'])
def admin_api_mark_message_read(message_id):
    if not admin_required():
        return jsonify({'success': False}), 403
    if banking_system.mark_admin_message_read(message_id):
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Message not found'}), 404

@app.route('/admin/api/stats', methods=['GET'])
def admin_api_stats():
    if not admin_required():
        return jsonify({'success': False}), 403
    stats = banking_system.get_all_stats()
    return jsonify({
        'success': True,
        'total_accounts': stats['total_accounts'],
        'total_customers': stats['total_customers'],
        'total_deposits': stats['total_deposits'],
        'total_balance': stats['total_balance'],
        'total_withdrawals': stats['total_withdrawals'],
        'monthly_trends': stats['monthly_trends'],
        'account_distribution': stats['account_distribution'],
        'loan_overview': stats['loan_overview'],
        'beneficiaries': stats['beneficiaries'],
        'low_balance_count': stats['low_balance_count'],
        'generated_at': stats['generated_at'],
    })

@app.route('/admin/api/users', methods=['POST'])
def admin_create_user():
    if not admin_required():
        return jsonify({'success': False}), 403
    try:
        data = request.json
        full_name = data['full_name'].strip()
        username = data['username'].strip()
        phone_number = data['phone_number'].strip()
        password = data['password'].strip()
        normalized_phone = banking_system.normalize_phone_number(phone_number)
        if not all([full_name, username, phone_number, password]):
            return jsonify({'success': False, 'message': 'All fields required'})
        if not normalized_phone:
            return jsonify({'success': False, 'message': 'Valid PH mobile number required'})
        if banking_system.get_user_by_phone(normalized_phone):
            return jsonify({'success': False, 'message': 'Phone number already exists'})
        if banking_system.register(full_name, username, password, normalized_phone):
            return jsonify({'success': True})
        return jsonify({'success': False, 'message': 'Username already exists'})
    except:
        return jsonify({'success': False, 'message': 'Invalid data'})

# ── User API ───────────────────────────────────────────────────

@app.route('/api/profile/update', methods=['POST'])
def api_profile_update():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    user = banking_system.get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    try:
        data = request.json
        full_name = data.get('full_name', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone_number', '').strip()
        photo = data.get('photo', '').strip()
        if full_name:
            user.full_name = full_name
        if email:
            user.email = email
        if phone:
            normalized = banking_system.normalize_phone_number(phone)
            if normalized:
                user.phone_number = normalized
        if photo:
            user.photo = photo
        banking_system._save_users()
        return jsonify({'success': True, 'full_name': user.full_name,
                        'email': user.email,
                        'phone_number': banking_system.format_phone_number(user.phone_number),
                        'photo': user.photo})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/profile/change-password', methods=['POST'])
def api_change_password():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    user = banking_system.get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    try:
        data = request.json
        current = data.get('current_password', '')
        new_pw = data.get('new_password', '')
        confirm = data.get('confirm_password', '')
        if not user.check_password(current):
            return jsonify({'success': False, 'message': 'Current password is incorrect'})
        if len(new_pw) < 6:
            return jsonify({'success': False, 'message': 'Password must be at least 6 characters'})
        if new_pw != confirm:
            return jsonify({'success': False, 'message': 'Passwords do not match'})
        user.password_hash = user._hash_password(new_pw)
        banking_system._save_users()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/deposit', methods=['POST'])
def api_deposit():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    try:
        amount = float(request.json['amount'])
        account_type = request.json.get('account_type', 'savings')
        if banking_system.deposit(amount, account_type):
            u = banking_system.get_current_user()
            return jsonify({'success': True, 'balance': u.account.balance,
                            'savings_balance': u.account.savings_balance,
                            'current_balance': u.account.current_balance})
        return jsonify({'success': False, 'message': 'Invalid amount'})
    except:
        return jsonify({'success': False, 'message': 'Invalid amount'})

@app.route('/api/withdraw', methods=['POST'])
def api_withdraw():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    try:
        amount = float(request.json['amount'])
        account_type = request.json.get('account_type', 'savings')
        if banking_system.withdraw(amount, account_type):
            u = banking_system.get_current_user()
            return jsonify({'success': True, 'balance': u.account.balance,
                            'savings_balance': u.account.savings_balance,
                            'current_balance': u.account.current_balance})
        return jsonify({'success': False, 'message': 'Insufficient funds'})
    except:
        return jsonify({'success': False, 'message': 'Invalid amount'})

@app.route('/api/send', methods=['POST'])
def api_send():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    user = banking_system.get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    try:
        data = request.json or {}
        amount = float(data.get('amount', 0))
        recipient = data.get('recipient', '').strip()
        note = data.get('note', '').strip()
        if not recipient:
            return jsonify({'success': False, 'message': 'Enter recipient mobile number'})
        success, message, receipt = banking_system.send_money(amount, recipient, note)
        if not success:
            return jsonify({'success': False, 'message': message})

        recipient_user = banking_system.get_user_by_username(receipt['recipient'])
        reference_seed = f"{receipt['sender']}-{receipt['recipient']}-{receipt['timestamp']}-{amount}"
        reference = 'PEV-' + hashlib.sha1(reference_seed.encode()).hexdigest()[:10].upper()
        return jsonify({
            'success': True,
            'message': message,
            'balance': user.account.balance,
            'savings_balance': user.account.savings_balance,
            'current_balance': user.account.current_balance,
            'receipt': {
                'reference': reference,
                'sender_name': user.full_name,
                'recipient_name': recipient_user.full_name if recipient_user else receipt['recipient'],
                'recipient_phone': banking_system.format_phone_number(recipient_user.phone_number) if recipient_user else recipient,
                'amount': amount,
                'note': note,
                'timestamp': receipt['timestamp']
            }
        })
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Invalid amount'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/send-message-to-admin', methods=['POST'])
def api_send_message_to_admin():
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    user = banking_system.get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    try:
        data = request.json
        message = data.get('message', '').strip()
        if not message:
            return jsonify({'success': False, 'message': 'Message cannot be empty'})
        banking_system.add_admin_message(user, message)
        subject = f'Message from {user.full_name} ({user.username})'
        html = f'<p><strong>From:</strong> {escape(user.full_name)} ({escape(user.username)})</p><p><strong>Message:</strong></p><p>{escape(message)}</p>'
        success, error = send_brevo_email(ADMIN_CONTACT_EMAIL, subject, html)
        if success:
            return jsonify({'success': True})
        return jsonify({'success': True, 'email_sent': False, 'message': error or 'Message saved, but email delivery failed'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/deposit')
def deposit():
    if 'username' not in session:
        return redirect(url_for('login'))
    user = banking_system.get_current_user()
    if not user:
        return redirect(url_for('login'))
    deposit_transactions = [
        txn for txn in reversed(user.account.transactions)
        if txn.type == 'DEPOSIT'
    ][:5]
    return render_template(
        'deposit.html',
        balance=user.account.balance,
        savings_balance=user.account.savings_balance,
        current_balance=user.account.current_balance,
        full_name=user.full_name,
        username=user.username,
        phone_number=banking_system.format_phone_number(user.phone_number),
        account_number=get_account_number(user.username),
        deposit_transactions=deposit_transactions,
        deposit_count=sum(1 for txn in user.account.transactions if txn.type == 'DEPOSIT'),
        total_deposited=sum(txn.amount for txn in user.account.transactions if txn.type == 'DEPOSIT'),
        admin_email=ADMIN_CONTACT_EMAIL,
    )

@app.route('/withdraw')
def withdraw():
    if 'username' not in session:
        return redirect(url_for('login'))
    user = banking_system.get_current_user()
    if not user:
        return redirect(url_for('login'))
    return render_template('withdraw.html', balance=user.account.balance,
                           savings_balance=user.account.savings_balance,
                           current_balance=user.account.current_balance,
                           full_name=user.full_name,
                           admin_email=ADMIN_CONTACT_EMAIL)

@app.route('/send')
def send():
    if 'username' not in session:
        return redirect(url_for('login'))
    user = banking_system.get_current_user()
    if not user:
        return redirect(url_for('login'))
    contacts = [
        {
            'full_name': u.full_name,
            'phone_number': banking_system.format_phone_number(u.phone_number)
        }
        for u in banking_system.users.values()
        if u.username != user.username and not u.is_admin
    ]
    return render_template(
        'send.html',
        balance=user.account.balance,
        savings_balance=user.account.savings_balance,
        full_name=user.full_name,
        phone_number=banking_system.format_phone_number(user.phone_number),
        contacts=contacts,
        admin_email=ADMIN_CONTACT_EMAIL
    )

@app.route('/logout')
def logout():
    session.pop('username', None)
    banking_system.logout()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.debug = False
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
