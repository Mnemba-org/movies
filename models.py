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
    google_id = db.Column(db.String(100), unique=True, nullable=True)
    profile_picture = db.Column(db.String(300), nullable=True)

    # User's purchases
    purchases = db.relationship(
        'Purchase',
        backref='user',
        lazy=True,
        cascade='all, delete-orphan'
    )


class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    video_path = db.Column(db.String(300))
    thumbnail = db.Column(db.String(300))
    title = db.Column(db.String(50), nullable=False)

    # True = free movie, False = paid movie
    free = db.Column(db.Boolean, default=False)

    # Movie price in TZS
    # Paid movies should normally be 700 TSh
    price = db.Column(db.Numeric(10, 2), default=700.00, nullable=False)

    date_posted = db.Column(db.DateTime, default=datetime.utcnow)

    # Purchases for this movie
    purchases = db.relationship(
        'Purchase',
        backref='video',
        lazy=True
    )


class Series(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)

    # True = free series, False = paid series
    free = db.Column(db.Boolean, default=False)

    # Series price in TZS
    # Paid series should normally be 1500 TSh
    price = db.Column(db.Numeric(10, 2), default=1500.00, nullable=False)

    thumbnail = db.Column(db.String(300))
    created_at = db.Column(
        db.DateTime,
        default=db.func.current_timestamp()
    )
    date_posted = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    episodes = db.relationship(
        'Episode',
        backref='series',
        cascade='all, delete-orphan',
        lazy=True
    )

    # Purchases for this series
    purchases = db.relationship(
        'Purchase',
        backref='series',
        lazy=True
    )


class Episode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    episode_number = db.Column(db.Integer, nullable=False)
    video_path = db.Column(db.String(300))

    series_id = db.Column(
        db.Integer,
        db.ForeignKey('series.id', ondelete='CASCADE'),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=db.func.current_timestamp()
    )


class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    # User who made the purchase
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=False
    )

    # Purchased movie
    # NULL when this purchase is for a series
    video_id = db.Column(
        db.Integer,
        db.ForeignKey('video.id'),
        nullable=True
    )

    # Purchased series
    # NULL when this purchase is for a movie
    series_id = db.Column(
        db.Integer,
        db.ForeignKey('series.id'),
        nullable=True
    )

    # "movie" or "series"
    item_type = db.Column(
        db.String(20),
        nullable=False
    )

    # Amount actually paid
    amount = db.Column(
        db.Numeric(10, 2),
        nullable=False
    )

    # Our unique reference sent to Pesapal
    merchant_reference = db.Column(
        db.String(100),
        nullable=False,
        unique=True
    )

    # Pesapal's transaction tracking ID
    order_tracking_id = db.Column(
        db.String(100),
        nullable=True
    )

    # Pending, Completed, Failed, etc.
    payment_status = db.Column(
        db.String(30),
        default='Pending',
        nullable=False
    )

    # When the purchase was made
    purchased_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # When access expires
    # For our current system:
    # Movie = 30 days
    # Series = 30 days
    expires_at = db.Column(
        db.DateTime,
        nullable=True
    )

    def is_active(self):
        """
        Returns True if this purchase is successfully paid
        and has not expired.
        """
        return (
            self.payment_status == 'Completed'
            and self.expires_at is not None
            and self.expires_at > datetime.utcnow()
        )
