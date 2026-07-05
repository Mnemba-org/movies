from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()
class User(db.Model, UserMixin):
    __tablename__ = 'user'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    # FIXED: Made nullable=True so Google users can register password-free without crashing
    password = db.Column(db.String(200), nullable=True) 
    is_admin = db.Column(db.Boolean, default=False)
    
    # Relationships
    purchases = db.relationship('MoviePurchase', backref='user', lazy=True)

class Video(db.Model):
    __tablename__ = 'video'
    
    id = db.Column(db.Integer, primary_key=True)
    video_path = db.Column(db.String(300))
    thumbnail = db.Column(db.String(300))
    title = db.Column(db.String(50), nullable=False)
    free = db.Column(db.Boolean, default=False)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)

class Series(db.Model):
    __tablename__ = 'series'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    free = db.Column(db.Boolean, default=False)
    thumbnail = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    date_posted = db.Column(db.DateTime, default=datetime.utcnow) # Duplicate column cleanup completed
    
    # Relationships
    episodes = db.relationship('Episode', backref='series', cascade='all, delete-orphan', lazy=True)

class Episode(db.Model):
    __tablename__ = 'episode'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    episode_number = db.Column(db.Integer, nullable=False)
    video_path = db.Column(db.String(300))
    series_id = db.Column(db.Integer, db.ForeignKey('series.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

# NEW MODEL TABLE: Safely tracks your 500 Tsh pay-per-movie customer transactions!
class MoviePurchase(db.Model):
    __tablename__ = 'movie_purchases'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    purchase_date = db.Column(db.DateTime, default=datetime.utcnow)
    merchant_reference = db.Column(db.String(100), unique=True, nullable=False) # Maps straight to Pesapal receipts
class Subscription(db.Model):
    __tablename__ = 'subscription'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    plan_type = db.Column(db.String(20), nullable=False)  # 'weekly' or 'monthly'
    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    end_date = db.Column(db.DateTime, nullable=False)
    merchant_reference = db.Column(db.String(100))
    
    user = db.relationship('User', backref='subscriptions')
