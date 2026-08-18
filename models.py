from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin


db = SQLAlchemy()


# ============================================================
# USER
# ============================================================

class User(db.Model, UserMixin):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    username = db.Column(
        db.String(100),
        unique=True,
        nullable=False
    )

    email = db.Column(
        db.String(120),
        unique=True,
        nullable=False
    )

    # Nullable because Google users may not have a password
    password = db.Column(
        db.String(200),
        nullable=True
    )

    is_admin = db.Column(
        db.Boolean,
        default=False
    )

    google_id = db.Column(
        db.String(100),
        unique=True,
        nullable=True
    )

    profile_picture = db.Column(
        db.String(300),
        nullable=True
    )

    # --------------------------------------------------------
    # USER PURCHASES
    # --------------------------------------------------------

    purchases = db.relationship(
        'Purchase',
        backref='user',
        lazy=True,
        cascade='all, delete-orphan'
    )


# ============================================================
# VIDEO / SINGLE MOVIE
# ============================================================

class Video(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    video_path = db.Column(
        db.String(300)
    )

    thumbnail = db.Column(
        db.String(300)
    )

    title = db.Column(
        db.String(50),
        nullable=False
    )

    # --------------------------------------------------------
    # FREE / PAID
    # --------------------------------------------------------
    # True  = Free movie
    # False = Paid movie

    free = db.Column(
        db.Boolean,
        default=False
    )

    # --------------------------------------------------------
    # MOVIE PRICE
    # --------------------------------------------------------
    # Default paid movie price = 1,000 TSh

    price = db.Column(
        db.Numeric(10, 2),
        default=1000.00,
        nullable=False
    )

    date_posted = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    # --------------------------------------------------------
    # MOVIE PURCHASES
    # --------------------------------------------------------

    purchases = db.relationship(
        'Purchase',
        backref='video',
        lazy=True
    )


# ============================================================
# SERIES
# ============================================================

class Series(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    title = db.Column(
        db.String(100),
        nullable=False
    )

    description = db.Column(
        db.Text
    )

    # --------------------------------------------------------
    # FREE / PAID
    # --------------------------------------------------------
    # True  = Free series
    # False = Paid series

    free = db.Column(
        db.Boolean,
        default=False
    )

    # --------------------------------------------------------
    # SERIES PRICE
    # --------------------------------------------------------
    # Default paid series price = 2,000 TSh

    price = db.Column(
        db.Numeric(10, 2),
        default=2000.00,
        nullable=False
    )

    thumbnail = db.Column(
        db.String(300)
    )

    created_at = db.Column(
        db.DateTime,
        default=db.func.current_timestamp()
    )

    date_posted = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    # --------------------------------------------------------
    # EPISODES
    # --------------------------------------------------------

    episodes = db.relationship(
        'Episode',
        backref='series',
        cascade='all, delete-orphan',
        lazy=True
    )

    # --------------------------------------------------------
    # SERIES PURCHASES
    # --------------------------------------------------------

    purchases = db.relationship(
        'Purchase',
        backref='series',
        lazy=True
    )


# ============================================================
# EPISODE
# ============================================================

class Episode(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    title = db.Column(
        db.String(100),
        nullable=False
    )

    episode_number = db.Column(
        db.Integer,
        nullable=False
    )

    video_path = db.Column(
        db.String(300)
    )

    series_id = db.Column(
        db.Integer,
        db.ForeignKey(
            'series.id',
            ondelete='CASCADE'
        ),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=db.func.current_timestamp()
    )


# ============================================================
# PURCHASE
# ============================================================

class Purchase(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # --------------------------------------------------------
    # USER
    # --------------------------------------------------------

    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=False
    )

    # --------------------------------------------------------
    # MOVIE
    # --------------------------------------------------------
    # NULL when purchase is for a series

    video_id = db.Column(
        db.Integer,
        db.ForeignKey('video.id'),
        nullable=True
    )

    # --------------------------------------------------------
    # SERIES
    # --------------------------------------------------------
    # NULL when purchase is for a movie

    series_id = db.Column(
        db.Integer,
        db.ForeignKey('series.id'),
        nullable=True
    )

    # --------------------------------------------------------
    # ITEM TYPE
    # --------------------------------------------------------
    # "movie" or "series"

    item_type = db.Column(
        db.String(20),
        nullable=False
    )

    # --------------------------------------------------------
    # AMOUNT PAID
    # --------------------------------------------------------

    amount = db.Column(
        db.Numeric(10, 2),
        nullable=False
    )

    # --------------------------------------------------------
    # MERCHANT REFERENCE
    # --------------------------------------------------------
    # Unique reference sent to Pesapal

    merchant_reference = db.Column(
        db.String(100),
        nullable=False,
        unique=True
    )

    # --------------------------------------------------------
    # PESAPAL TRACKING ID
    # --------------------------------------------------------

    order_tracking_id = db.Column(
        db.String(100),
        nullable=True
    )

    # --------------------------------------------------------
    # PAYMENT STATUS
    # --------------------------------------------------------
    # Pending
    # Completed
    # Failed
    # etc.

    payment_status = db.Column(
        db.String(30),
        default='Pending',
        nullable=False
    )

    # --------------------------------------------------------
    # PURCHASE DATE
    # --------------------------------------------------------

    purchased_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # --------------------------------------------------------
    # ACCESS EXPIRATION
    # --------------------------------------------------------
    # Both movies and series have 30 days of access.
    #
    # The actual 30-day period is calculated in payment.py
    # when Pesapal confirms the payment.

    expires_at = db.Column(
        db.DateTime,
        nullable=True
    )

    # --------------------------------------------------------
    # CHECK ACTIVE PURCHASE
    # --------------------------------------------------------

    def is_active(self):

        """
        Returns True if this purchase:
        1. Was successfully paid
        2. Has an expiration date
        3. Has not expired yet
        """

        return (
            self.payment_status == 'Completed'
            and
            self.expires_at is not None
            and
            self.expires_at > datetime.utcnow()
        )
