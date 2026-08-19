from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    current_app,
    jsonify,
    send_from_directory
)

from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user
)

from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename
from functools import wraps

import os
import uuid

from flask_mail import Mail, Message
from fuzzywuzzy import fuzz

import boto3
from botocore.config import Config

from flask_migrate import Migrate

from itsdangerous import URLSafeTimedSerializer

from authlib.integrations.flask_client import OAuth

from datetime import datetime, timedelta

from models import (
    db,
    User,
    Video,
    Series,
    Episode,
    Purchase
)


# ============================================================
# FLASK APP SETUP
# ============================================================

app = Flask(
    __name__,
    template_folder='templates'
)

app.config['SECRET_KEY'] = os.environ.get(
    'SECRET_KEY',
    'your_secret_key_here'
)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'mydb'
)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


# ============================================================
# UPLOAD CONFIGURATION
# ============================================================

UPLOAD_FOLDER = 'static/uploads'

ALLOWED_EXTENSIONS = {
    'mp4',
    'avi',
    'mkv',
    'mov',
    'webm',
    'jpg',
    'jpeg',
    'png',
    'gif',
    'vob'
}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


# ============================================================
# CLOUDFLARE R2 CONFIGURATION
# ============================================================

app.config['R2_ACCESS_KEY'] = os.environ.get(
    'R2_ACCESS_KEY'
)

app.config['R2_SECRET_KEY'] = os.environ.get(
    'R2_SECRET_KEY'
)

app.config['R2_BUCKET'] = os.environ.get(
    'R2_BUCKET'
)

app.config['R2_ENDPOINT'] = os.environ.get(
    'R2_ENDPOINT'
)

app.config['R2_PUBLIC_URL'] = os.environ.get(
    'R2_PUBLIC_URL'
)


# ============================================================
# GOOGLE OAUTH CONFIGURATION
# ============================================================

app.config['GOOGLE_CLIENT_ID'] = os.environ.get(
    'GOOGLE_CLIENT_ID'
)

app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get(
    'GOOGLE_CLIENT_SECRET'
)

app.config['GOOGLE_DISCOVERY_URL'] = (
    'https://accounts.google.com/.well-known/openid-configuration'
)


# ============================================================
# REMEMBER LOGIN CONFIGURATION
# ============================================================

app.config['REMEMBER_COOKIE_DURATION'] = timedelta(
    days=36500
)

app.config['REMEMBER_COOKIE_HTTPONLY'] = True

app.config['REMEMBER_COOKIE_SECURE'] = True

app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'


# ============================================================
# EMAIL CONFIGURATION
# ============================================================

app.config['MAIL_SERVER'] = 'smtp.gmail.com'

app.config['MAIL_PORT'] = 587

app.config['MAIL_USE_TLS'] = True

app.config['MAIL_USERNAME'] = os.environ.get(
    'MAIL_USERNAME'
)

app.config['MAIL_PASSWORD'] = os.environ.get(
    'MAIL_PASSWORD'
)


# ============================================================
# EXTENSIONS
# ============================================================

mail = Mail(app)

db.init_app(app)

bcrypt = Bcrypt(app)

migrate = Migrate(app, db)


# ============================================================
# GOOGLE OAUTH
# ============================================================

oauth = OAuth(app)

google = oauth.register(
    name='google',

    client_id=app.config['GOOGLE_CLIENT_ID'],

    client_secret=app.config['GOOGLE_CLIENT_SECRET'],

    server_metadata_url=(
        'https://accounts.google.com/'
        '.well-known/openid-configuration'
    ),

    client_kwargs={
        'scope': 'openid email profile'
    }
)


# ============================================================
# LOGIN MANAGER
# ============================================================

login_manager = LoginManager()

login_manager.init_app(app)

login_manager.login_view = 'login'


# ============================================================
# DATABASE COLUMN CHECK
# ============================================================

def ensure_supabase_columns():

    """
    Ensure required Google columns exist
    in the Supabase user table.
    """

    try:

        with app.app_context():

            from sqlalchemy import inspect, text

            inspector = inspect(db.engine)

            columns = [
                col['name']
                for col in inspector.get_columns('user')
            ]

            migrations_run = False

            # ------------------------------------------------
            # GOOGLE ID
            # ------------------------------------------------

            if 'google_id' not in columns:

                print(
                    '🔧 Adding google_id column...'
                )

                db.session.execute(
                    text(
                        'ALTER TABLE "user" '
                        'ADD COLUMN IF NOT EXISTS '
                        'google_id VARCHAR(100) UNIQUE'
                    )
                )

                db.session.execute(
                    text(
                        'CREATE INDEX IF NOT EXISTS '
                        'idx_user_google_id '
                        'ON "user"(google_id)'
                    )
                )

                migrations_run = True

                print(
                    '✓ google_id column added'
                )

            # ------------------------------------------------
            # PROFILE PICTURE
            # ------------------------------------------------

            if 'profile_picture' not in columns:

                print(
                    '🔧 Adding profile_picture column...'
                )

                db.session.execute(
                    text(
                        'ALTER TABLE "user" '
                        'ADD COLUMN IF NOT EXISTS '
                        'profile_picture VARCHAR(300)'
                    )
                )

                migrations_run = True

                print(
                    '✓ profile_picture column added'
                )

            # ------------------------------------------------
            # PASSWORD NULLABLE
            # ------------------------------------------------

            password_is_nullable = True

            for col in inspector.get_columns('user'):

                if col['name'] == 'password':

                    password_is_nullable = col.get(
                        'nullable',
                        True
                    )

                    break

            if not password_is_nullable:

                print(
                    '🔧 Making password column nullable...'
                )

                db.session.execute(
                    text(
                        'ALTER TABLE "user" '
                        'ALTER COLUMN password '
                        'DROP NOT NULL'
                    )
                )

                migrations_run = True

                print(
                    '✓ password column is now nullable'
                )

            # ------------------------------------------------
            # COMMIT
            # ------------------------------------------------

            if migrations_run:

                db.session.commit()

                print(
                    '✅ Database migration completed successfully!'
                )

            else:

                print(
                    '✅ Database schema is up to date'
                )

    except Exception as e:

        print(
            f'⚠️ Migration error: {e}'
        )

        try:

            db.session.rollback()

        except Exception:

            pass

        print(
            '''
⚠️ Please run this SQL in Supabase SQL Editor:

ALTER TABLE "user"
ADD COLUMN IF NOT EXISTS google_id VARCHAR(100) UNIQUE;

ALTER TABLE "user"
ADD COLUMN IF NOT EXISTS profile_picture VARCHAR(300);

ALTER TABLE "user"
ALTER COLUMN password DROP NOT NULL;

CREATE INDEX IF NOT EXISTS
idx_user_google_id
ON "user"(google_id);
'''
        )


# ============================================================
# INITIAL DATABASE SETUP
# ============================================================

with app.app_context():

    ensure_supabase_columns()

    db.create_all()

    os.makedirs(
        os.path.join(
            app.config['UPLOAD_FOLDER'],
            'series'
        ),
        exist_ok=True
    )

    os.makedirs(
        os.path.join(
            app.config['UPLOAD_FOLDER'],
            'thumbnails'
        ),
        exist_ok=True
    )


# ============================================================
# CLOUDFLARE R2 FUNCTIONS
# ============================================================

def get_r2_client():

    """
    Initialize and return Cloudflare R2 client.
    """

    return boto3.client(
        's3',

        aws_access_key_id=app.config[
            'R2_ACCESS_KEY'
        ],

        aws_secret_access_key=app.config[
            'R2_SECRET_KEY'
        ],

        endpoint_url=app.config[
            'R2_ENDPOINT'
        ],

        config=Config(
            signature_version='s3v4'
        ),

        region_name='auto'
    )


def delete_from_r2(object_key):

    """
    Delete a file from R2 bucket.
    """

    try:

        s3_client = get_r2_client()

        s3_client.delete_object(
            Bucket=app.config['R2_BUCKET'],
            Key=object_key
        )

        print(
            f'Deleted from R2: {object_key}'
        )

        return True

    except Exception as e:

        print(
            f'Error deleting from R2: {e}'
        )

        return False


def get_content_type(filename):

    """
    Determine content type based on file extension.
    """

    ext = os.path.splitext(
        filename
    )[1].lower()

    content_types = {

        '.mp4': 'video/mp4',

        '.avi': 'video/x-msvideo',

        '.mkv': 'video/x-matroska',

        '.mov': 'video/quicktime',

        '.webm': 'video/webm',

        '.jpg': 'image/jpeg',

        '.jpeg': 'image/jpeg',

        '.png': 'image/png',

        '.gif': 'image/gif',

        '.vob': 'video/dvd'
    }

    return content_types.get(
        ext,
        'application/octet-stream'
    )


def upload_to_r2(
    file_data,
    filename,
    folder='videos'
):

    """
    Upload file to Cloudflare R2.
    """

    try:

        s3_client = get_r2_client()

        object_key = (
            f'{folder}/{filename}'
        )

        s3_client.upload_fileobj(

            file_data,

            app.config['R2_BUCKET'],

            object_key,

            ExtraArgs={
                'ContentType': get_content_type(
                    filename
                )
            }
        )

        return (
            f"{app.config['R2_PUBLIC_URL']}"
            f"/{object_key}"
        )

    except Exception as e:

        print(
            f'Error uploading to R2: {e}'
        )

        return None


# ============================================================
# GENERAL HELPERS
# ============================================================

def allowed_file(filename):

    return (
        '.'
        in filename
        and
        filename.rsplit(
            '.',
            1
        )[1].lower()
        in ALLOWED_EXTENSIONS
    )


def get_token(email):

    serializer = URLSafeTimedSerializer(
        app.secret_key
    )

    return serializer.dumps(
        email,
        salt='reset'
    )


def verify_token(token):

    serializer = URLSafeTimedSerializer(
        app.secret_key
    )

    try:

        return serializer.loads(
            token,
            salt='reset',
            max_age=3600
        )

    except Exception:

        return None


def admin_required(f):

    @wraps(f)
    def decorated_function(*args, **kwargs):

        if not current_user.is_authenticated:

            return redirect(
                url_for('login')
            )

        if not current_user.is_admin:

            return 'Access denied', 403

        return f(*args, **kwargs)

    return decorated_function


def create_series_folder(series_name):

    """
    Create a folder name for a series.
    """

    folder_name = secure_filename(
        series_name.replace(
            ' ',
            '_'
        ).lower()
    )

    series_path = os.path.join(
        app.config['UPLOAD_FOLDER'],
        'series',
        folder_name
    )

    os.makedirs(
        series_path,
        exist_ok=True
    )

    return series_path, folder_name


# ============================================================
# PURCHASE SETTINGS
# ============================================================
#
# MOVIE:
#       700 TSh
#
# SERIES:
#       1,500 TSh
#
# VALIDITY:
#       30 DAYS
#
# IMPORTANT:
#
# payment.py is responsible for creating the Purchase record.
#
# A completed Purchase should contain:
#
#   payment_status = "Completed"
#   purchased_at = datetime.utcnow()
#   expires_at = purchased_at + timedelta(days=30)
#
# ============================================================

MOVIE_PRICE = 700

SERIES_PRICE = 1500

PURCHASE_DURATION_DAYS = 30


# ============================================================
# GET ACTIVE MOVIE PURCHASE
# ============================================================

def get_active_movie_purchase(
    user_id,
    video_id
):

    """
    Return the latest active completed movie purchase.
    """

    now = datetime.utcnow()

    return Purchase.query.filter(

        Purchase.user_id == user_id,

        Purchase.video_id == video_id,

        Purchase.item_type == 'movie',

        Purchase.payment_status == 'Completed',

        Purchase.expires_at > now

    ).order_by(

        Purchase.expires_at.desc()

    ).first()


# ============================================================
# GET ACTIVE SERIES PURCHASE
# ============================================================

def get_active_series_purchase(
    user_id,
    series_id
):

    """
    Return the latest active completed series purchase.
    """

    now = datetime.utcnow()

    return Purchase.query.filter(

        Purchase.user_id == user_id,

        Purchase.series_id == series_id,

        Purchase.item_type == 'series',

        Purchase.payment_status == 'Completed',

        Purchase.expires_at > now

    ).order_by(

        Purchase.expires_at.desc()

    ).first()


# ============================================================
# CHECK MOVIE ACCESS
# ============================================================

def has_movie_access(
    user_id,
    video_id
):

    """
    Check whether the user has active access
    to the movie.
    """

    purchase = get_active_movie_purchase(
        user_id,
        video_id
    )

    return purchase is not None


# ============================================================
# CHECK SERIES ACCESS
# ============================================================

def has_series_access(
    user_id,
    series_id
):

    """
    Check whether the user has active access
    to the series.
    """

    purchase = get_active_series_purchase(
        user_id,
        series_id
    )

    return purchase is not None


# ============================================================
# GET REMAINING PURCHASE TIME
# ============================================================

def get_purchase_days_left(purchase):

    """
    Return the number of days remaining.

    Example:

        30 days purchased
        -> 30

        10 days remaining
        -> 10

        expired
        -> 0
    """

    if not purchase:

        return 0

    if not purchase.expires_at:

        return 0

    now = datetime.utcnow()

    remaining = (
        purchase.expires_at - now
    )

    if remaining.total_seconds() <= 0:

        return 0

    return remaining.days + (
        1 if remaining.seconds > 0 else 0
    )


# ============================================================
# SITEMAP
# ============================================================

@app.route('/sitemap.xml')
def serve_root_sitemap():

    return send_from_directory(
        os.getcwd(),
        'sitemap.xml',
        mimetype='application/xml'
    )


# ============================================================
# USER MANAGEMENT
# ============================================================

@login_manager.user_loader
def load_user(user_id):

    try:

        return User.query.get(
            int(user_id)
        )

    except Exception:

        return None


# ============================================================
# DATETIME CONTEXT
# ============================================================

@app.context_processor
def inject_datetime():

    return {
        'datetime': datetime
    }


# ============================================================
# PURCHASE CONTEXT
# ============================================================

@app.context_processor
def inject_purchase_data():

    return {

        'now': datetime.utcnow,

        'movie_price': MOVIE_PRICE,

        'series_price': SERIES_PRICE,

        'purchase_duration_days':
            PURCHASE_DURATION_DAYS
    }


# ============================================================
# GOOGLE LOGIN
# ============================================================

@app.route('/login')
def login():

    """
    Redirect user to Google OAuth login.
    """

    redirect_uri = url_for(
        'google_callback',
        _external=True
    )

    return google.authorize_redirect(
        redirect_uri
    )


# ============================================================
# GOOGLE CALLBACK
# ============================================================

@app.route('/login/google')
def google_callback():

    """
    Handle Google OAuth callback.
    """

    try:

        token = google.authorize_access_token()

        resp = google.get(
            'https://openidconnect.googleapis.com/v1/userinfo'
        )

        user_info = resp.json()

        if not user_info:

            flash(
                'Failed to get user information from Google.',
                'error'
            )

            return redirect(
                url_for('home')
            )

        email = user_info.get(
            'email'
        )

        google_id = user_info.get(
            'sub'
        )

        name = user_info.get(
            'name',
            email.split('@')[0]
        )

        profile_picture = user_info.get(
            'picture'
        )

        if not email:

            flash(
                'Email not provided by Google.',
                'error'
            )

            return redirect(
                url_for('home')
            )

        # ----------------------------------------------------
        # FIND USER BY GOOGLE ID
        # ----------------------------------------------------

        user = User.query.filter_by(
            google_id=google_id
        ).first()

        # ----------------------------------------------------
        # FIND USER BY EMAIL
        # ----------------------------------------------------

        if not user:

            user = User.query.filter_by(
                email=email
            ).first()

            if user:

                user.google_id = google_id

                if profile_picture:

                    user.profile_picture = (
                        profile_picture
                    )

                db.session.commit()

                print(
                    f'Linked Google account: {email}'
                )

        # ----------------------------------------------------
        # CREATE NEW USER
        # ----------------------------------------------------

        if not user:

            username = (
                name
                .replace(
                    ' ',
                    '_'
                )
                .lower()
            )

            existing_user = User.query.filter_by(
                username=username
            ).first()

            if existing_user:

                username = (
                    f'{username}_'
                    f'{google_id[:6]}'
                )

            new_user = User(

                username=username,

                email=email,

                google_id=google_id,

                profile_picture=profile_picture,

                password=None,

                is_admin=False
            )

            db.session.add(
                new_user
            )

            db.session.commit()

            user = new_user

            print(
                f'Created new user: {email}'
            )

        # ----------------------------------------------------
        # LOGIN
        # ----------------------------------------------------

        login_user(
            user,
            remember=True
        )

        if user.is_admin:

            flash(
                f'Welcome back, {user.username}!',
                'success'
            )

            return redirect(
                url_for(
                    'admin_dashboard'
                )
            )

        flash(
            f'Welcome, {user.username}!',
            'success'
        )

        return redirect(
            url_for('home')
        )

    except Exception as e:

        print(
            f'Google login error: {e}'
        )

        flash(
            'An error occurred during Google login. Please try again.',
            'error'
        )

        return redirect(
            url_for('home')
        )


# ============================================================
# LOGOUT
# ============================================================

@app.route('/logout')
@login_required
def logout():

    logout_user()

    flash(
        'You have been logged out.',
        'info'
    )

    return redirect(
        url_for('home')
    )


# ============================================================
# HOME
# ============================================================

@app.route('/')
def home():

    videos = Video.query.all()

    series_list = Series.query.all()

    mixed_content = []

    # --------------------------------------------------------
    # MOVIES
    # --------------------------------------------------------

    for video in videos:

        mixed_content.append({

            'item': video,

            'type': 'video',

            'date': video.date_posted
        })

    # --------------------------------------------------------
    # SERIES
    # --------------------------------------------------------

    for series_item in series_list:

        mixed_content.append({

            'item': series_item,

            'type': 'series',

            'date': series_item.date_posted
        })

    # --------------------------------------------------------
    # SORT NEWEST FIRST
    # --------------------------------------------------------

    mixed_content.sort(
        key=lambda x: x['date'],
        reverse=True
    )

    return render_template(
        'home.html',
        mixed_content=mixed_content
    )


# ============================================================
# WATCH SERIES
# ============================================================

@app.route(
    '/watch_series/<int:series_id>'
)
@login_required
def series(series_id):

    series_item = Series.query.get_or_404(
        series_id
    )

    episodes = (
        Episode.query
        .filter_by(
            series_id=series_id
        )
        .order_by(
            Episode.episode_number
        )
        .all()
    )

    # --------------------------------------------------------
    # FREE SERIES
    # --------------------------------------------------------

    if series_item.free:

        return render_template(
            'series.html',
            series=series_item,
            episodes=episodes
        )

    # --------------------------------------------------------
    # PAID SERIES
    # --------------------------------------------------------

    if not has_series_access(

        current_user.id,

        series_item.id

    ):

        return redirect(
            url_for(
                'payment.buy_series',
                series_id=series_item.id
            )
        )

    return render_template(
        'series.html',
        series=series_item,
        episodes=episodes
    )


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route('/admin_dashboard')
@login_required
@admin_required
def admin_dashboard():

    videos = Video.query.all()

    return render_template(
        'aploadvideos.html',
        videos=videos
    )


# ============================================================
# UPLOAD MOVIE
# ============================================================

@app.route(
    '/upload',
    methods=['GET', 'POST']
)
@admin_required
def post():

    if request.method == 'POST':

        title = request.form.get(
            'title',
            ''
        ).strip()

        video = request.files.get(
            'video'
        )

        image = request.files.get(
            'thumbnail'
        )

        if not video or not image:

            flash(
                'Please upload both video and thumbnail.',
                'error'
            )

            return redirect(
                request.url
            )

        video_filename = video.filename

        image_filename = image.filename

        if not allowed_file(
            video_filename
        ):

            flash(
                'Video file type not allowed.',
                'error'
            )

            return redirect(
                request.url
            )

        if not allowed_file(
            image_filename
        ):

            flash(
                'Thumbnail file type not allowed.',
                'error'
            )

            return redirect(
                request.url
            )

        # ----------------------------------------------------
        # GENERATE UNIQUE FILE NAMES
        # ----------------------------------------------------

        video_filename = (
            str(uuid.uuid4())
            +
            os.path.splitext(
                video_filename
            )[1].lower()
        )

        image_filename = (
            str(uuid.uuid4())
            +
            os.path.splitext(
                image_filename
            )[1].lower()
        )

        # ----------------------------------------------------
        # UPLOAD VIDEO
        # ----------------------------------------------------

        video_url = upload_to_r2(
            video,
            video_filename,
            'videos'
        )

        if not video_url:

            flash(
                'Error uploading video to cloud storage.',
                'error'
            )

            return redirect(
                request.url
            )

        # ----------------------------------------------------
        # UPLOAD THUMBNAIL
        # ----------------------------------------------------

        thumbnail_url = upload_to_r2(
            image,
            image_filename,
            'thumbnails'
        )

        if not thumbnail_url:

            flash(
                'Error uploading thumbnail to cloud storage.',
                'error'
            )

            return redirect(
                request.url
            )

        # ----------------------------------------------------
        # FREE / PAID
        # ----------------------------------------------------

        free = (
            'free'
            in request.form
        )

        # ----------------------------------------------------
        # CREATE MOVIE
        # ----------------------------------------------------

        new_video = Video(

            title=title,

            video_path=video_url,

            thumbnail=thumbnail_url,

            free=free
        )

        db.session.add(
            new_video
        )

        db.session.commit()

        flash(
            'Video uploaded successfully to cloud storage!',
            'success'
        )

        return redirect(
            url_for(
                'admin_dashboard'
            )
        )

    return render_template(
        'aploadvideos.html'
    )


# ============================================================
# ADD SERIES
# ============================================================

@app.route(
    '/add_series',
    methods=['GET', 'POST']
)
@admin_required
def add_series():

    if request.method == 'POST':

        title = request.form.get(
            'title',
            ''
        ).strip()

        description = request.form.get(
            'description',
            ''
        )

        thumbnail = request.files.get(
            'thumbnail'
        )

        thumbnail_url = None

        # ----------------------------------------------------
        # UPLOAD SERIES THUMBNAIL
        # ----------------------------------------------------

        if (
            thumbnail
            and
            thumbnail.filename
        ):

            if not allowed_file(
                thumbnail.filename
            ):

                flash(
                    'Thumbnail file type not allowed.',
                    'error'
                )

                return redirect(
                    request.url
                )

            thumbnail_filename = (
                str(uuid.uuid4())
                +
                os.path.splitext(
                    thumbnail.filename
                )[1].lower()
            )

            thumbnail_url = upload_to_r2(
                thumbnail,
                thumbnail_filename,
                'series_covers'
            )

            if not thumbnail_url:

                flash(
                    'Error uploading thumbnail to cloud storage.',
                    'error'
                )

                return redirect(
                    request.url
                )

        # ----------------------------------------------------
        # FREE / PAID
        # ----------------------------------------------------

        free = (
            'free'
            in request.form
        )

        # ----------------------------------------------------
        # CREATE SERIES
        # ----------------------------------------------------

        new_series = Series(

            title=title,

            description=description,

            thumbnail=thumbnail_url,

            free=free
        )

        db.session.add(
            new_series
        )

        db.session.commit()

        flash(
            f'Series "{title}" added successfully!',
            'success'
        )

        return redirect(
            url_for(
                'add_episodes',
                series_id=new_series.id
            )
        )

    return render_template(
        'add_series.html'
    )


# ============================================================
# ADD EPISODES
# ============================================================

@app.route(
    '/add_episodes/<int:series_id>/',
    methods=['GET', 'POST']
)
@admin_required
def add_episodes(series_id):

    series_item = Series.query.get_or_404(
        series_id
    )

    folder_name = secure_filename(
        series_item.title.replace(
            ' ',
            '_'
        ).lower()
    )

    series_folder = (
        f'series/{folder_name}'
    )

    if request.method == 'POST':

        episode_title = request.form.get(
            'title',
            ''
        ).strip()

        episode_number = request.form.get(
            'episode_number'
        )

        video_file = request.files.get(
            'video'
        )

        if not video_file:

            flash(
                'Please select a video file.',
                'error'
            )

            return redirect(
                request.url
            )

        if not video_file.filename:

            flash(
                'Please select a video file.',
                'error'
            )

            return redirect(
                request.url
            )

        if not allowed_file(
            video_file.filename
        ):

            flash(
                'Video file type not allowed.',
                'error'
            )

            return redirect(
                request.url
            )

        # ----------------------------------------------------
        # EPISODE FILE NAME
        # ----------------------------------------------------

        original_filename = secure_filename(
            video_file.filename
        )

        video_filename = (
            f'ep{episode_number}_'
            f'{original_filename}'
        )

        # ----------------------------------------------------
        # UPLOAD EPISODE
        # ----------------------------------------------------

        video_url = upload_to_r2(
            video_file,
            video_filename,
            series_folder
        )

        if not video_url:

            flash(
                'Error uploading episode to cloud storage.',
                'error'
            )

            return redirect(
                request.url
            )

        # ----------------------------------------------------
        # CREATE EPISODE
        # ----------------------------------------------------

        new_episode = Episode(

            title=episode_title,

            episode_number=episode_number,

            video_path=video_url,

            series_id=series_id
        )

        db.session.add(
            new_episode
        )

        db.session.commit()

        flash(
            f'Episode {episode_number} added successfully!',
            'success'
        )

        # ----------------------------------------------------
        # ADD ANOTHER
        # ----------------------------------------------------

        if 'add_another' in request.form:

            return redirect(
                url_for(
                    'add_episodes',
                    series_id=series_id
                )
            )

        return redirect(
            url_for(
                'view_series',
                series_id=series_id
            )
        )

    return render_template(
        'add_episodes.html',
        series=series_item
    )


# ============================================================
# DELETE MOVIE
# ============================================================

@app.route(
    '/delete_video/<int:id>',
    methods=['POST']
)
@admin_required
def delete_video(id):

    video = Video.query.get_or_404(
        id
    )

    # --------------------------------------------------------
    # DELETE VIDEO FROM R2
    # --------------------------------------------------------

    if (
        video.video_path
        and
        app.config['R2_PUBLIC_URL']
        and
        app.config['R2_PUBLIC_URL']
        in video.video_path
    ):

        object_key = video.video_path.replace(
            f"{app.config['R2_PUBLIC_URL']}/",
            ''
        )

        delete_from_r2(
            object_key
        )

    # --------------------------------------------------------
    # DELETE THUMBNAIL FROM R2
    # --------------------------------------------------------

    if (
        video.thumbnail
        and
        app.config['R2_PUBLIC_URL']
        and
        app.config['R2_PUBLIC_URL']
        in video.thumbnail
    ):

        object_key = video.thumbnail.replace(
            f"{app.config['R2_PUBLIC_URL']}/",
            ''
        )

        delete_from_r2(
            object_key
        )

    # --------------------------------------------------------
    # DELETE PURCHASES FOR MOVIE
    # --------------------------------------------------------

    Purchase.query.filter_by(
        video_id=video.id
    ).delete(
        synchronize_session=False
    )

    # --------------------------------------------------------
    # DELETE MOVIE
    # --------------------------------------------------------

    db.session.delete(
        video
    )

    db.session.commit()

    flash(
        'Video deleted successfully from cloud storage!',
        'success'
    )

    return redirect(
        url_for(
            'admin_dashboard'
        )
    )


# ============================================================
# SERIES MANAGEMENT
# ============================================================

@app.route('/index')
@admin_required
def index():

    series_list = Series.query.all()

    return render_template(
        'index.html',
        series_list=series_list
    )


# ============================================================
# VIEW SERIES
# ============================================================

@app.route(
    '/series/<int:series_id>'
)
def view_series(series_id):

    series_item = Series.query.get_or_404(
        series_id
    )

    episodes = (
        Episode.query
        .filter_by(
            series_id=series_id
        )
        .order_by(
            Episode.episode_number
        )
        .all()
    )

    return render_template(
        'view_series.html',
        series=series_item,
        episodes=episodes
    )


# ============================================================
# SEARCH
# ============================================================

@app.route('/search')
def search():

    query = request.args.get(
        'query',
        ''
    ).lower().strip()

    if not query:

        return redirect(
            url_for('home')
        )

    all_videos = Video.query.all()

    all_series = Series.query.all()

    # --------------------------------------------------------
    # EXACT MATCH
    # --------------------------------------------------------

    exact_videos = [

        v for v in all_videos

        if query in v.title.lower()
    ]

    exact_series = [

        s for s in all_series

        if query in s.title.lower()
    ]

    videos = []

    series_list = []

    if exact_videos or exact_series:

        videos = exact_videos

        series_list = exact_series

    else:

        # ----------------------------------------------------
        # FUZZY MOVIE SEARCH
        # ----------------------------------------------------

        for video in all_videos:

            title = video.title.lower()

            similarity = fuzz.ratio(
                query,
                title
            )

            partial_ratio = fuzz.partial_ratio(
                query,
                title
            )

            token_sort_ratio = fuzz.token_sort_ratio(
                query,
                title
            )

            best_score = max(
                similarity,
                partial_ratio,
                token_sort_ratio
            )

            if best_score > 50:

                videos.append(
                    video
                )

        # ----------------------------------------------------
        # FUZZY SERIES SEARCH
        # ----------------------------------------------------

        for series_item in all_series:

            title = series_item.title.lower()

            similarity = fuzz.ratio(
                query,
                title
            )

            partial_ratio = fuzz.partial_ratio(
                query,
                title
            )

            token_sort_ratio = fuzz.token_sort_ratio(
                query,
                title
            )

            best_score = max(
                similarity,
                partial_ratio,
                token_sort_ratio
            )

            if best_score > 50:

                series_list.append(
                    series_item
                )

    return render_template(

        'search_results.html',

        videos=videos,

        series=series_list,

        query=request.args.get(
            'query',
            ''
        )
    )


# ============================================================
# DELETE SERIES
# ============================================================

@app.route(
    '/delete_series/<int:series_id>',
    methods=['POST']
)
@admin_required
def delete_series(series_id):

    series_item = Series.query.get_or_404(
        series_id
    )

    episodes = Episode.query.filter_by(
        series_id=series_id
    ).all()

    # --------------------------------------------------------
    # DELETE EPISODES FROM R2
    # --------------------------------------------------------

    for episode in episodes:

        if (
            episode.video_path
            and
            app.config['R2_PUBLIC_URL']
            and
            app.config['R2_PUBLIC_URL']
            in episode.video_path
        ):

            object_key = episode.video_path.replace(
                f"{app.config['R2_PUBLIC_URL']}/",
                ''
            )

            delete_from_r2(
                object_key
            )

        db.session.delete(
            episode
        )

    # --------------------------------------------------------
    # DELETE SERIES THUMBNAIL
    # --------------------------------------------------------

    if (
        series_item.thumbnail
        and
        app.config['R2_PUBLIC_URL']
        and
        app.config['R2_PUBLIC_URL']
        in series_item.thumbnail
    ):

        object_key = series_item.thumbnail.replace(
            f"{app.config['R2_PUBLIC_URL']}/",
            ''
        )

        delete_from_r2(
            object_key
        )

    # --------------------------------------------------------
    # DELETE ENTIRE SERIES FOLDER
    # --------------------------------------------------------

    folder_name = secure_filename(
        series_item.title.replace(
            ' ',
            '_'
        ).lower()
    )

    series_folder = (
        f'series/{folder_name}'
    )

    try:

        s3_client = get_r2_client()

        paginator = s3_client.get_paginator(
            'list_objects_v2'
        )

        for page in paginator.paginate(
            Bucket=app.config['R2_BUCKET'],
            Prefix=series_folder
        ):

            for obj in page.get(
                'Contents',
                []
            ):

                delete_from_r2(
                    obj['Key']
                )

    except Exception as e:

        print(
            f'Error deleting series folder: {e}'
        )

    # --------------------------------------------------------
    # DELETE SERIES PURCHASES
    # --------------------------------------------------------

    Purchase.query.filter_by(
        series_id=series_item.id
    ).delete(
        synchronize_session=False
    )

    # --------------------------------------------------------
    # DELETE SERIES
    # --------------------------------------------------------

    db.session.delete(
        series_item
    )

    db.session.commit()

    flash(
        'Series and all episodes deleted successfully!',
        'success'
    )

    return redirect(
        url_for('index')
    )


# ============================================================
# SINGLE MOVIES
# ============================================================

@app.route('/single_movies')
def single_movies():

    videos = Video.query.all()

    return render_template(
        'choose_single.html',
        videos=videos
    )


# ============================================================
# CHOOSE SERIES
# ============================================================

@app.route('/choose_series')
def choose_series():

    series_list = Series.query.all()

    return render_template(
        'choose_series.html',
        series_list=series_list
    )


# ============================================================
# FORGOT PASSWORD
# ============================================================

@app.route(
    '/forgot',
    methods=['GET', 'POST']
)
def forgot():

    if request.method == 'POST':

        email = request.form.get(
            'email',
            ''
        ).strip().lower()

        user = User.query.filter_by(
            email=email
        ).first()

        if user:

            token = get_token(
                email
            )

            link = url_for(
                'reset',
                token=token,
                _external=True
            )

            msg = Message(

                'Reset Password',

                recipients=[email]
            )

            msg.body = (
                f'Click the following link '
                f'to reset your password:\n\n'
                f'{link}'
            )

            try:

                mail.send(
                    msg
                )

                flash(
                    'Check your email for the password reset link.',
                    'info'
                )

            except Exception as e:

                print(
                    f'Email error: {e}'
                )

                flash(
                    'Unable to send reset email.',
                    'error'
                )

        else:

            flash(
                'If an account exists with that email, '
                'a reset link will be sent.',
                'info'
            )

        return redirect(
            url_for('login')
        )

    return """
    <!DOCTYPE html>

    <html>

    <head>

        <title>
            Forgot Password
        </title>

    </head>

    <body
        style="
        font-family:Arial;
        text-align:center;
        margin-top:100px;
        "
    >

        <h2>
            Forgot Password
        </h2>

        <form method="post">

            <input
                type="email"
                name="email"
                placeholder="Your email"
                required
            >

            <br><br>

            <button type="submit">
                Send Reset Link
            </button>

        </form>

        <br>

        <a href="/login">
            Back
        </a>

    </body>

    </html>
    """


# ============================================================
# RESET PASSWORD
# ============================================================

@app.route(
    '/reset/<token>',
    methods=['GET', 'POST']
)
def reset(token):

    email = verify_token(
        token
    )

    if not email:

        return (
            'Link invalid or expired. '
            '<a href="/forgot">Try again</a>'
        )

    if request.method == 'POST':

        password = request.form.get(
            'password',
            ''
        )

        if not password:

            return (
                'Password cannot be empty. '
                '<a href="">Try again</a>'
            )

        hashed = (
            bcrypt
            .generate_password_hash(
                password
            )
            .decode('utf-8')
        )

        user = User.query.filter_by(
            email=email
        ).first()

        if user:

            user.password = hashed

            db.session.commit()

            return (
                'Password updated! '
                '<a href="/login">Login now</a>'
            )

        return (
            'User not found. '
            '<a href="/forgot">Try again</a>'
        )

    return """
    <!DOCTYPE html>

    <html>

    <head>

        <title>
            Create New Password
        </title>

    </head>

    <body
        style="
        font-family:Arial;
        text-align:center;
        margin-top:100px;
        "
    >

        <h2>
            Create New Password
        </h2>

        <form method="post">

            <input
                type="password"
                name="password"
                placeholder="New password"
                required
            >

            <br><br>

            <button type="submit">
                Reset Password
            </button>

        </form>

    </body>

    </html>
    """


# ============================================================
# WATCH MOVIE
# ============================================================

@app.route(
    '/video/<int:video_id>'
)
@login_required
def movie(video_id):

    video = Video.query.get_or_404(
        video_id
    )

    # --------------------------------------------------------
    # FREE MOVIE
    # --------------------------------------------------------

    if video.free:

        return redirect(
            video.video_path
        )

    # --------------------------------------------------------
    # PAID MOVIE
    # --------------------------------------------------------

    if not has_movie_access(

        current_user.id,

        video.id

    ):

        return redirect(
            url_for(
                'payment.buy_movie',
                video_id=video.id
            )
        )

    # --------------------------------------------------------
    # USER HAS VALID PURCHASE
    # --------------------------------------------------------

    return redirect(
        video.video_path
    )


# ============================================================
# PAYMENT BLUEPRINT
# ============================================================
#
# payment.py handles:
#
#   - Movie purchase
#   - Series purchase
#   - Payment processing
#   - Creating Purchase records
#
# ============================================================

try:

    from payment import payment

    app.register_blueprint(
        payment,
        url_prefix='/payment'
    )

    print(
        '✅ Payment system loaded successfully.'
    )

except ImportError as e:

    print(
        f'⚠️ Payment system could not be loaded: {e}'
    )
# ============================================================
# INVITATION BLUEPRINT
# ============================================================

try:

    from invitation import invitation

    app.register_blueprint(
        invitation
    )

    print(
        '✅ Invitation / Zawadi system loaded successfully.'
    )

except ImportError as e:

    print(
        f'⚠️ invitation.py could not be loaded: {e}'
    )

# ============================================================
# RUN APP
# ============================================================

if __name__ == '__main__':

    app.run(

        debug=False,

        host='0.0.0.0',

        port=int(
            os.environ.get(
                'PORT',
                5000
            )
        )
    )
