import hashlib
import json
import os
import re
import secrets
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from flask import session


class Transaction:
    def __init__(self, type, amount, recipient=None, timestamp=None, id=None):
        self.type = type
        self.amount = amount
        self.recipient = recipient
        self.timestamp = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.id = id or secrets.token_hex(4)

    def to_dict(self):
        return {
            'type': self.type,
            'amount': self.amount,
            'recipient': self.recipient,
            'timestamp': self.timestamp,
            'id': self.id
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            type=data.get('type', 'UNKNOWN'),
            amount=data.get('amount', 0.0),
            recipient=data.get('recipient'),
            timestamp=data.get('timestamp'),
            id=data.get('id')
        )


class Account:
    def __init__(self):
        self.savings_balance = 0.0
        self.current_balance = 0.0
        self.transactions: List[Transaction] = []

    @property
    def balance(self):
        return self.savings_balance + self.current_balance

    def to_dict(self):
        return {
            'savings_balance': self.savings_balance,
            'current_balance': self.current_balance,
            'transactions': [txn.to_dict() for txn in self.transactions]
        }

    @classmethod
    def from_dict(cls, data):
        account = cls()
        account.savings_balance = float(data.get('savings_balance', data.get('balance', 0.0)))
        account.current_balance = float(data.get('current_balance', 0.0))
        transactions = data.get('transactions', []) or []
        account.transactions = [Transaction.from_dict(txn) for txn in transactions]
        return account


class User:
    def __init__(self, full_name, username, password, phone_number="", email="", is_admin=False):
        self.full_name = full_name
        self.username = username
        self.phone_number = phone_number
        self.email = email
        self.photo = ""
        self.password_hash = hashlib.sha256(password.encode()).hexdigest()
        self.is_admin = is_admin
        self.account = Account()

    def check_password(self, password):
        return self.password_hash == hashlib.sha256(password.encode()).hexdigest()

    def _hash_password(self, password):
        return hashlib.sha256(password.encode()).hexdigest()

    def to_dict(self):
        return {
            'full_name': self.full_name,
            'username': self.username,
            'phone_number': self.phone_number,
            'email': self.email,
            'photo': self.photo,
            'password_hash': self.password_hash,
            'is_admin': self.is_admin,
            'account': self.account.to_dict()
        }

    @classmethod
    def from_dict(cls, data):
        user = cls(
            full_name=data.get('full_name', ''),
            username=data.get('username', ''),
            password=data.get('password', ''),
            phone_number=data.get('phone_number', ''),
            email=data.get('email', ''),
            is_admin=data.get('is_admin', False)
        )
        if data.get('password_hash'):
            user.password_hash = data['password_hash']
        user.photo = data.get('photo', '')
        user.account = Account.from_dict(data.get('account', {}))
        return user


class BankingSystem:
    def __init__(self):
        self.users: Dict[str, User] = {}
        self.current_session = None
        self.data_file = Path(__file__).resolve().parent / 'users.json'
        self.messages_file = Path(__file__).resolve().parent / 'admin_messages.json'
        self._load_users()
        self._ensure_admin_account()

    def _ensure_admin_account(self):
        if any(user.is_admin for user in self.users.values()):
            return
        admin_username = os.getenv('ADMIN_USERNAME', 'admin')
        admin_password = os.getenv('ADMIN_PASSWORD', 'admin123')
        if not admin_username or not admin_password:
            return
        admin_email = os.getenv('ADMIN_EMAIL', 'admin@pevbanking.com')
        admin_phone = os.getenv('ADMIN_PHONE', '09000000000')
        self.users[admin_username] = User(
            full_name='Administrator',
            username=admin_username,
            password=admin_password,
            phone_number=admin_phone,
            email=admin_email,
            is_admin=True
        )
        self._save_users()

    def _load_users(self):
        if not self.data_file.exists():
            return
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            for user_data in raw:
                user = User.from_dict(user_data)
                self.users[user.username] = user
        except Exception:
            pass

    def _save_users(self):
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump([user.to_dict() for user in self.users.values()], f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def register(self, full_name, username, password, phone, email=""):
        if username in self.users:
            return False
        normalized_phone = self.normalize_phone_number(phone)
        if not normalized_phone:
            return False
        if self.get_user_by_phone(normalized_phone):
            return False
        if email and self.get_user_by_email(email):
            return False
        user = User(full_name, username, password, normalized_phone, email=email)
        self.users[username] = user
        self._save_users()
        return True

    def login(self, username, password):
        if username in self.users and self.users[username].check_password(password):
            self.current_session = self.users[username]
            return True
        return False

    def logout(self):
        self.current_session = None

    def get_current_user(self):
        if self.current_session:
            return self.current_session
        username = session.get('username')
        if username and username in self.users:
            self.current_session = self.users[username]
            return self.current_session
        return None

    def get_user_by_username(self, username):
        return self.users.get(username)

    def get_user_by_phone(self, normalized_phone):
        for user in self.users.values():
            if user.phone_number == normalized_phone:
                return user
        return None

    def get_user_by_email(self, email):
        normalized_email = email.strip().lower()
        for user in self.users.values():
            if user.email.strip().lower() == normalized_email:
                return user
        return None

    def _load_admin_messages(self):
        if not self.messages_file.exists():
            return []
        try:
            with open(self.messages_file, 'r', encoding='utf-8') as file:
                messages = json.load(file)
            return messages if isinstance(messages, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _save_admin_messages(self, messages):
        with open(self.messages_file, 'w', encoding='utf-8') as file:
            json.dump(messages, file, indent=2)

    def add_admin_message(self, user, message):
        messages = self._load_admin_messages()
        item = {
            'id': secrets.token_hex(4),
            'username': user.username,
            'full_name': user.full_name,
            'phone_number': self.format_phone_number(user.phone_number),
            'message': message,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'read': False
        }
        messages.insert(0, item)
        self._save_admin_messages(messages)
        return item

    def get_admin_messages(self):
        return self._load_admin_messages()

    def mark_admin_message_read(self, message_id):
        messages = self._load_admin_messages()
        changed = False
        for item in messages:
            if item.get('id') == message_id:
                item['read'] = True
                changed = True
                break
        if changed:
            self._save_admin_messages(messages)
        return changed

    def normalize_phone_number(self, phone):
        if not phone:
            return None
        digits = re.sub(r'\D', '', phone)
        if digits.startswith('0') and len(digits) == 11:
            return '+63' + digits[1:]
        if digits.startswith('63') and len(digits) == 12:
            return '+' + digits
        if digits.startswith('9') and len(digits) == 10:
            return '+63' + digits
        if digits.startswith('+63') and len(digits) == 13:
            return digits
        return None

    def format_phone_number(self, normalized_phone):
        if not normalized_phone:
            return ''
        digits = re.sub(r'\D', '', normalized_phone)
        if digits.startswith('63') and len(digits) == 12:
            return '0' + digits[2:]
        if digits.startswith('9') and len(digits) == 10:
            return '0' + digits
        return normalized_phone

    def get_all_stats(self):
        transactions = []
        total_deposits = 0.0
        total_withdrawals = 0.0
        total_balance = 0.0
        low_balance_count = 0
        users = []

        for user in self.users.values():
            if user.is_admin:
                continue
            users.append(user)
            balance = user.account.balance
            total_balance += balance
            if balance < 1000:
                low_balance_count += 1
            for txn in user.account.transactions:
                transactions.append({'user': user.username, 'txn': txn})
                if txn.type == 'DEPOSIT' and txn.amount > 0:
                    total_deposits += txn.amount
                if txn.type in ['WITHDRAW', 'TRANSFER'] and txn.amount < 0:
                    total_withdrawals += abs(txn.amount)

        all_transactions = sorted(transactions, key=lambda item: item['txn'].timestamp, reverse=True)
        recent_transactions = all_transactions[:5]

        monthly_trends = []
        account_distribution = {
            'low': sum(1 for user in users if user.account.balance < 1000),
            'medium': sum(1 for user in users if 1000 <= user.account.balance < 10000),
            'high': sum(1 for user in users if user.account.balance >= 10000)
        }

        return {
            'total_accounts': len(self.users),
            'total_customers': len(users),
            'total_deposits': total_deposits,
            'total_balance': total_balance,
            'total_withdrawals': total_withdrawals,
            'monthly_trends': monthly_trends,
            'account_distribution': account_distribution,
            'loan_overview': {},
            'beneficiaries': [],
            'low_balance_count': low_balance_count,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'recent_transactions': recent_transactions,
            'all_transactions': all_transactions,
            'users': users
        }

    def deposit(self, amount, account_type='savings'):
        if amount <= 0 or self.current_session is None:
            return False
        if account_type == 'current':
            self.current_session.account.current_balance += amount
        else:
            self.current_session.account.savings_balance += amount
        self.current_session.account.transactions.append(Transaction('DEPOSIT', amount))
        self._save_users()
        return True

    def withdraw(self, amount, account_type='savings'):
        if amount <= 0 or self.current_session is None:
            return False
        account = self.current_session.account
        if account_type == 'current':
            if account.current_balance < amount:
                return False
            account.current_balance -= amount
        else:
            if account.savings_balance < amount:
                return False
            account.savings_balance -= amount
        account.transactions.append(Transaction('WITHDRAW', -amount))
        self._save_users()
        return True

    def get_recipient_user(self, recipient):
        if not recipient:
            return None
        recipient = recipient.strip()
        if recipient in self.users:
            return self.users[recipient]
        normalized = self.normalize_phone_number(recipient)
        if normalized:
            return self.get_user_by_phone(normalized)
        return None

    def send_money(self, amount, recipient, note=''):
        if amount <= 0 or self.current_session is None:
            return False, 'Invalid amount', None
        recipient_user = self.get_recipient_user(recipient)
        if not recipient_user:
            return False, 'Recipient not found', None
        if recipient_user.username == self.current_session.username:
            return False, 'Cannot send to yourself', None

        account = self.current_session.account
        if account.balance < amount:
            return False, 'Insufficient funds', None

        remaining = amount
        if account.current_balance >= remaining:
            account.current_balance -= remaining
            remaining = 0
        else:
            remaining -= account.current_balance
            account.current_balance = 0
        if remaining > 0:
            if account.savings_balance < remaining:
                return False, 'Insufficient funds', None
            account.savings_balance -= remaining

        account.transactions.append(Transaction('TRANSFER', -amount, recipient=recipient_user.username))
        if recipient_user.account.current_balance is None:
            recipient_user.account.current_balance = 0.0
        recipient_user.account.current_balance += amount
        recipient_user.account.transactions.append(Transaction('TRANSFER', amount, recipient=self.current_session.username))
        self._save_users()

        receipt = {
            'sender': self.current_session.username,
            'recipient': recipient_user.username,
            'amount': amount,
            'note': note,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        return True, f'Sent ₱{amount:.2f} to {recipient_user.full_name}', receipt
