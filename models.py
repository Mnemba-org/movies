from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=True)  # Nullable for Google users
    is_admin = db.Column(db.Boolean, default=False)
    google_id = db.Column(db.String(100), unique=True, nullable=True)  # Google ID
    profile_picture = db.Column(db.String(300), nullable=True)  # Profile picture URL
    Subscriptions = db.relationship('Subscription', backref='user', lazy=True)

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    video_path = db.Column(db.String(300))
    thumbnail = db.Column(db.String(300))
    title = db.Column(db.String(50), nullable=False)
    free = db.Column(db.Boolean)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)

class Series(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    free = db.Column(db.Boolean, default=False)
    thumbnail = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)
    episodes = db.relationship('Episode', backref='series', cascade='all, delete-orphan', lazy=True)

class Episode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    episode_number = db.Column(db.Integer, nullable=False)
    video_path = db.Column(db.String(300))
    series_id = db.Column(db.Integer, db.ForeignKey('series.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    plan_type = db.Column(db.String(20), nullable=False)
    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    end_date = db.Column(db.DateTime, nullable=False)
    merchant_reference = db.Column(db.String(100), nullable=True, unique=True)
