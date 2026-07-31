from flask import Flask, render_template, redirect, url_for, request, flash, current_app, jsonify, send_from_directory
import requests
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from functools import wraps
import os
import uuid
from flask_mail import Mail, Message
from fuzzywuzzy import fuzz, process
from models import Subscription, db, User, Video, Series, Episode
from datetime import datetime, timedelta
import boto3
from botocore.config import Config
from flask_migrate import Migrate
from itsdangerous import URLSafeTimedSerializer
from authlib.integrations.flask_client import OAuth

# ===== IMPORT THE PAYMENT BLUEPRINT =====
from payment_routes import payment_bp

# Flask App Setup
app = Flask(__name__, template_folder='templates')

# ===== SECURITY: Use environment variable for secret key =====
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your_secret_key_here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('mydb')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {
    'mp4', 'avi', 'mkv', 'mov', 'jpg', 'jpeg', 'png', 'gif', 'vob'
}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

app.config['R2_ACCESS_KEY'] = os.environ.get('R2_ACCESS_KEY')
app.config['R2_SECRET_KEY'] = os.environ.get('R2_SECRET_KEY')
app.config['R2_BUCKET'] = os.environ.get('R2_BUCKET')
app.config['R2_ENDPOINT'] = os.environ.get('R2_ENDPOINT')
app.config['R2_PUBLIC_URL'] = os.environ.get('R2_PUBLIC_URL')

# Pesapal Production Gateway Configurations
app.config['PESAPAL_CONSUMER_KEY'] = os.environ.get('PESAPAL_CONSUMER_KEY')
app.config['PESAPAL_CONSUMER_SECRET'] = os.environ.get('PESAPAL_CONSUMER_SECRET')
app.config['PESAPAL_BASE_URL'] = "https://pay.pesapal.com/v3"
app.config['APP_BASE_URL'] = os.environ.get('APP_BASE_URL', 'https://muvizetu.com')

# Google OAuth Configuration
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')
app.config['GOOGLE_DISCOVERY_URL'] = "https://accounts.google.com/.well-known/openid-configuration"

# Cookie Security Settings
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=36500)
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SECURE'] = True
app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')

# Initialize Extensions
mail = Mail(app)
db.init_app(app)
bcrypt = Bcrypt(app)

# OAuth setup
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=app.config['GOOGLE_CLIENT_ID'],
    client_secret=app.config['GOOGLE_CLIENT_SECRET'],
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# ===== REGISTER THE PAYMENT BLUEPRINT =====
app.register_blueprint(payment_bp)

# ===== DATABASE MIGRATION FUNCTION =====

def ensure_supabase_columns():
    """Ensure required columns exist in Supabase user table"""
    try:
        with app.app_context():
            from sqlalchemy import inspect, text
            
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('user')]
            
            migrations_run = False
            
            # Add google_id
            if 'google_id' not in columns:
                print("🔧 Adding google_id column...")
                db.session.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS google_id VARCHAR(100) UNIQUE'))
                db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_user_google_id ON "user"(google_id)'))
                migrations_run = True
                print("✓ google_id column added")
            
            # Add profile_picture
            if 'profile_picture' not in columns:
                print("🔧 Adding profile_picture column...")
                db.session.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS profile_picture VARCHAR(300)'))
                migrations_run = True
                print("✓ profile_picture column added")
            
            # Make password nullable
            password_is_nullable = True
            for col in inspector.get_columns('user'):
                if col['name'] == 'password':
                    password_is_nullable = col.get('nullable', True)
                    break
            
            if not password_is_nullable:
                print("🔧 Making password column nullable...")
                db.session.execute(text('ALTER TABLE "user" ALTER COLUMN password DROP NOT NULL'))
                migrations_run = True
                print("✓ password column is now nullable")
            
            if migrations_run:
                db.session.commit()
                print("✅ Database migration completed successfully!")
            else:
                print("✅ Database schema is up to date")
                
    except Exception as e:
        print(f"⚠️ Migration error: {e}")
        db.session.rollback()
        print("\n⚠️ Please run this SQL in Supabase SQL Editor:")
        print("""
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS google_id VARCHAR(100) UNIQUE;
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS profile_picture VARCHAR(300);
        ALTER TABLE "user" ALTER COLUMN password DROP NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_user_google_id ON "user"(google_id);
        """)

# ===== RUN MIGRATION =====
with app.app_context():
    ensure_supabase_columns()
    db.create_all()
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'series'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'thumbnails'), exist_ok=True)

# ===== HELPER FUNCTIONS =====

def delete_from_r2(object_key):
    """Delete a file from R2 bucket"""
    try:
        s3_client = get_r2_client()
        s3_client.delete_object(
            Bucket=app.config['R2_BUCKET'],
            Key=object_key)
        print(f"Deleted from R2: {object_key}")
        return True
    except Exception as e:
        print(f"Error deleting from R2: {e}")
        return False

def get_token(email):
    s = URLSafeTimedSerializer(app.secret_key)
    return s.dumps(email, salt="reset")

def verify_token(token):
    s = URLSafeTimedSerializer(app.secret_key)
    try:
        return s.loads(token, salt="reset", max_age=3600)
    except:
        return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_r2_client():
    """Initialize and return R2 client"""
    return boto3.client(
        's3',
        aws_access_key_id=app.config['R2_ACCESS_KEY'],
        aws_secret_access_key=app.config['R2_SECRET_KEY'],
        endpoint_url=app.config['R2_ENDPOINT'],
        config=Config(signature_version='s3v4'),
        region_name='auto'
    )

def get_content_type(filename):
    """Determine content type based on file extension"""
    ext = os.path.splitext(filename)[1].lower()
    content_types = {
        'mp4': 'video/mp4',
        'avi': 'video/x-msvideo',
        'mkv': 'video/x-matroska',
        'mov': 'video/quicktime',
        'webm': 'video/webm',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'vob': 'video/dvd',
    }
    return content_types.get(ext, 'application/octet-stream')

def upload_to_r2(file_data, filename, folder='videos'):
    """Upload file to R2 bucket"""
    try:
        s3_client = get_r2_client()
        object_key = f"{folder}/{filename}"
        s3_client.upload_fileobj(
            file_data,
            app.config["R2_BUCKET"],
            object_key,
            ExtraArgs={
                'ContentType': get_content_type(filename),
                'ACL': 'public-read'
            }
        )
        return f"{app.config['R2_PUBLIC_URL']}/{object_key}"
    except Exception as e:
        print(f"Error uploading to R2: {e}")
        return None

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if not current_user.is_admin:
            return "Access denied"
        return f(*args, **kwargs)
    return decorated_function

def create_series_folder(series_name):
    """Create a folder for the series in static/uploads/series/"""
    folder_name = secure_filename(series_name.replace(' ', '_').lower())
    series_path = os.path.join(app.config['UPLOAD_FOLDER'], 'series', folder_name)
    os.makedirs(series_path, exist_ok=True)
    return series_path, folder_name

def get_active_subscription(user_id):
    """Check if the user has an active subscription"""
    now = datetime.utcnow()
    return Subscription.query.filter(
        Subscription.user_id == user_id,
        Subscription.end_date > now).first()

def has_access(user_id):
    return get_active_subscription(user_id) is not None

def get_subscription_time_left(user_id):
    sub = Subscription.query.filter(
        Subscription.user_id == user_id,
        Subscription.end_date > datetime.utcnow()
    ).first()
    if not sub:
        return None, 0, 0, 0
    delta = sub.end_date - datetime.utcnow()
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    return sub, days, hours, minutes

# ===== USER LOADER =====

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===== CONTEXT PROCESSORS =====

@app.context_processor
def inject_datetime():
    return dict(datetime=datetime)

@app.context_processor
def inject_subscription():
    if current_user.is_authenticated:
        sub = get_active_subscription(current_user.id)
    else:
        sub = None
    return {
        'subscription': sub,
        'now': datetime.utcnow
    }

# ===== SITEMAP ROUTE =====

@app.route('/sitemap.xml')
def serve_root_sitemap():
    return send_from_directory(os.getcwd(), 'sitemap.xml', mimetype='application/xml')

# ===== GOOGLE OAUTH ROUTES =====

@app.route('/login')
def login():
    """Redirect to Google OAuth login"""
    redirect_uri = url_for('google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/login/google')
def google_callback():
    """Handle Google OAuth callback - Auto creates account if doesn't exist"""
    try:
        token = google.authorize_access_token()
        resp = google.get('https://openidconnect.googleapis.com/v1/userinfo')
        user_info = resp.json()
        
        if not user_info:
            flash('Failed to get user information from Google.', 'error')
            return redirect(url_for('home'))
        
        email = user_info.get('email')
        google_id = user_info.get('sub')
        name = user_info.get('name', email.split('@')[0])
        profile_picture = user_info.get('picture')
        
        if not email:
            flash('Email not provided by Google.', 'error')
            return redirect(url_for('home'))
        
        user = User.query.filter_by(google_id=google_id).first()
        
        if not user:
            user = User.query.filter_by(email=email).first()
            
            if user:
                user.google_id = google_id
                if profile_picture:
                    user.profile_picture = profile_picture
                db.session.commit()
                print(f"Linked Google account to existing user: {email}")
            else:
                username = name.replace(' ', '_').lower()
                existing_user = User.query.filter_by(username=username).first()
                if existing_user:
                    username = f"{username}_{google_id[:6]}"
                
                new_user = User(
                    username=username,
                    email=email,
                    google_id=google_id,
                    profile_picture=profile_picture,
                    password=None,
                    is_admin=False
                )
                db.session.add(new_user)
                db.session.commit()
                user = new_user
                print(f"Created new user automatically: {email}")
        
        login_user(user, remember=True)
        
        if user.is_admin:
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash(f'Welcome, {user.username}!', 'success')
            return redirect(url_for('home'))
            
    except Exception as e:
        print(f"Google login error: {e}")
        flash('An error occurred during Google login. Please try again.', 'error')
        return redirect(url_for('home'))

@app.route('/logout')
@login_required
def logout():
    """Logout user"""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))

# ===== FRONTEND ROUTES =====

@app.route('/')
def home():
    videos = Video.query.all()
    series_list = Series.query.all()
    mixed_content = []
    for video in videos:
        mixed_content.append({
            'item': video,
            'type': 'video',
            'date': video.date_posted
        })
    for series in series_list:
        mixed_content.append({
            'item': series,
            'type': 'series',
            'date': series.date_posted
        })
    mixed_content.sort(key=lambda x: x['date'], reverse=True)
    return render_template("home.html", mixed_content=mixed_content)

@app.route('/time_left')
@login_required
def days_left():
    sub, days, hours, minutes = get_subscription_time_left(current_user.id)
    return f"""
    <h1 style='text-align:center; font-size:50px;'>
    {days}d {hours}h {minutes}m
    </h1>
    """

@app.route('/watch_series/<int:series_id>')
@login_required
def series(series_id):
    series = Series.query.get_or_404(series_id)
    episodes = Episode.query.filter_by(series_id=series_id)\
        .order_by(Episode.episode_number).all()
    if not series.free and not has_access(current_user.id):
        return redirect(url_for('payment.subscribe'))
    return render_template('series.html', series=series, episodes=episodes)

@app.route('/my_subscription')
@login_required
def my_subscription():
    sub = get_active_subscription(current_user.id)
    return render_template('my_subscription.html', subscription=sub)

# ===== ADMIN SUBSCRIPTION ROUTES =====

@app.route('/admin_dashboard/add-subscription', methods=['GET', 'POST'])
@login_required
@admin_required
def add_subscription():
    if request.method == 'POST':
        email = request.form.get('email')
        plan = request.form.get('plan')
        user = User.query.filter_by(email=email).first()
        if not user:
            flash("User not found", "error")
            return redirect(url_for('add_subscription'))
        now = datetime.utcnow()
        if plan == "weekly":
            duration = timedelta(days=7)
        else:
            duration = timedelta(days=30)
        existing = Subscription.query.filter(
            Subscription.user_id == user.id,
            Subscription.end_date > now
        ).first()
        if existing:
            existing.end_date += duration
        else:
            new_sub = Subscription(
                user_id=user.id,
                plan_type=plan,
                start_date=now,
                end_date=now + duration
            )
            db.session.add(new_sub)
        db.session.commit()
        flash("Subscription added successfully!", "success")
        return redirect(url_for('add_subscription'))
    return render_template('add_subscription.html')
    
@app.route('/admin_dashboard/subscribers')
@login_required
@admin_required
def subscribers():
    subs = Subscription.query.all()
    return render_template('subscribers.html', subs=subs)

# ===== ADMIN DASHBOARD =====

@app.route('/admin_dashboard')
@login_required
@admin_required
def admin_dashboard():
    videos = Video.query.all()
    return render_template('aploadvideos.html', videos=videos)

@app.route('/upload', methods=['GET', 'POST'])
@login_required
@admin_required
def post():
    if request.method == 'POST':
        title = request.form['title']
        video = request.files['video']
        image = request.files['thumbnail']
        
        if not video or not image:
            flash('Please upload both video and thumbnail', 'error')
            return redirect(request.url)
        
        video_filename = video.filename
        image_filename = image.filename
        
        if not allowed_file(video_filename) or not allowed_file(image_filename):
            flash('File type not allowed', 'error')
            return redirect(request.url)
        
        video_filename = str(uuid.uuid4()) + os.path.splitext(video_filename)[1]
        image_filename = str(uuid.uuid4()) + os.path.splitext(image_filename)[1]
        
        video_url = upload_to_r2(video, video_filename, 'videos')
        if not video_url:
            flash('Error uploading video to cloud storage', 'error')
            return redirect(request.url)
        
        thumbnail_url = upload_to_r2(image, image_filename, 'thumbnails')
        if not thumbnail_url:
            flash('Error uploading thumbnail to cloud storage', 'error')
            return redirect(request.url)
        
        free = 'free' in request.form
        new_video = Video(
            title=title,
            video_path=video_url,
            thumbnail=thumbnail_url,
            free=free
        )
        db.session.add(new_video)
        db.session.commit()
        flash('Video uploaded successfully to cloud storage!', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('aploadvideos.html')

# ===== SERIES MANAGEMENT =====

@app.route('/add_series', methods=['GET', 'POST'])
@login_required
@admin_required
def add_series():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form.get('description', '')
        thumbnail = request.files.get('thumbnail')
        thumbnail_url = None
        
        if thumbnail and thumbnail.filename and allowed_file(thumbnail.filename):
            thumbnail_filename = str(uuid.uuid4()) + os.path.splitext(thumbnail.filename)[1]
            thumbnail_url = upload_to_r2(thumbnail, thumbnail_filename, 'series_covers')
            if not thumbnail_url:
                flash('Error uploading thumbnail to cloud storage', 'error')
                return redirect(request.url)
        
        free = 'free' in request.form
        new_series = Series(
            title=title,
            description=description,
            thumbnail=thumbnail_url,
            free=free
        )
        db.session.add(new_series)
        db.session.commit()
        flash(f'Series "{title}" added successfully!', 'success')
        return redirect(url_for('add_episodes', series_id=new_series.id))
    return render_template('add_series.html')

@app.route('/add_episodes/<int:series_id>/', methods=['GET', 'POST'])
@login_required
@admin_required
def add_episodes(series_id):
    series = Series.query.get_or_404(series_id)
    folder_name = secure_filename(series.title.replace(' ', '_').lower())
    series_folder = f"series/{folder_name}"
    
    if request.method == 'POST':
        episode_title = request.form['title']
        episode_number = request.form['episode_number']
        video_file = request.files['video']
        video_url = None
        
        if video_file and video_file.filename:
            if allowed_file(video_file.filename):
                video_filename = f"ep{episode_number}_{secure_filename(video_file.filename)}"
                video_url = upload_to_r2(video_file, video_filename, series_folder)
                if not video_url:
                    flash('Error uploading episode to cloud storage', 'error')
                    return redirect(request.url)
            else:
                flash('File type not allowed', 'error')
                return redirect(request.url)
        else:
            flash('Please select a video file', 'error')
            return redirect(request.url)
        
        new_episode = Episode(
            title=episode_title,
            episode_number=episode_number,
            video_path=video_url,
            series_id=series_id
        )
        db.session.add(new_episode)
        db.session.commit()
        flash(f'Episode {episode_number} added successfully to cloud storage!', 'success')
        
        if 'add_another' in request.form:
            return redirect(url_for('add_episodes', series_id=series_id))
        return redirect(url_for('view_series', series_id=series_id))
    return render_template('add_episodes.html', series=series)

@app.route('/delete_video/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_video(id):
    video = Video.query.get_or_404(id)
    if video.video_path and app.config['R2_PUBLIC_URL'] in video.video_path:
        object_key = video.video_path.replace(f"{app.config['R2_PUBLIC_URL']}/", "")
        delete_from_r2(object_key)
    if video.thumbnail and app.config['R2_PUBLIC_URL'] in video.thumbnail:
        object_key = video.thumbnail.replace(f"{app.config['R2_PUBLIC_URL']}/", "")
        delete_from_r2(object_key)
    db.session.delete(video)
    db.session.commit()
    flash("Video deleted successfully from cloud storage!", 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/index')
@login_required
@admin_required
def index():
    series_list = Series.query.all()
    return render_template('index.html', series_list=series_list)

@app.route('/series/<int:series_id>')
def view_series(series_id):
    series = Series.query.get_or_404(series_id)
    episodes = Episode.query.filter_by(series_id=series_id).order_by(Episode.episode_number).all()
    return render_template('view_series.html', series=series, episodes=episodes)

@app.route('/delete_series/<int:series_id>', methods=['POST'])
@login_required
@admin_required
def delete_series(series_id):
    series = Series.query.get_or_404(series_id)
    episodes = Episode.query.filter_by(series_id=series_id).all()
    
    for episode in episodes:
        if episode.video_path and app.config['R2_PUBLIC_URL'] in episode.video_path:
            object_key = episode.video_path.replace(f"{app.config['R2_PUBLIC_URL']}/", "")
            delete_from_r2(object_key)
        db.session.delete(episode)
    
    if series.thumbnail and app.config['R2_PUBLIC_URL'] in series.thumbnail:
        object_key = series.thumbnail.replace(f"{app.config['R2_PUBLIC_URL']}/", "")
        delete_from_r2(object_key)
    
    folder_name = secure_filename(series.title.replace(' ', '_').lower())
    series_folder = f"series/{folder_name}"
    
    try:
        s3_client = get_r2_client()
        objects = s3_client.list_objects_v2(
            Bucket=app.config['R2_BUCKET'],
            Prefix=series_folder
        )
        if 'Contents' in objects:
            for obj in objects['Contents']:
                delete_from_r2(obj['Key'])
    except Exception as e:
        print(f"Error deleting series folder: {e}")
    
    db.session.delete(series)
    db.session.commit()
    flash('Series and all episodes deleted successfully from cloud storage!', 'success')
    return redirect(url_for('index'))

@app.route('/single_movies')
def single_movies():
    videos = Video.query.all()
    return render_template('choose_single.html', videos=videos)

@app.route('/choose_series')
def choose_series():
    series_list = Series.query.all()
    return render_template('choose_series.html', series_list=series_list)

@app.route('/video/<int:video_id>')
@login_required
def movie(video_id):
    video = Video.query.get_or_404(video_id)
    if not video.free and not has_access(current_user.id):
        return redirect(url_for('payment.subscribe'))
    return redirect(video.video_path)

# ===== SEARCH ROUTE =====

@app.route('/search')
def search():
    query = request.args.get('query', "").lower().strip()
    if not query:
        return redirect(url_for('home'))
    
    all_videos = Video.query.all()
    all_series = Series.query.all()
    
    exact_videos = [v for v in all_videos if query in v.title.lower()]
    exact_series = [s for s in all_series if query in s.title.lower()]
    
    videos = []
    series_list = []
    
    if exact_videos or exact_series:
        videos = exact_videos
        series_list = exact_series
    else:
        video_titles = [(v.id, v.title.lower()) for v in all_videos]
        for video_id, title in video_titles:
            similarity = fuzz.ratio(query, title)
            partial_ratio = fuzz.partial_ratio(query, title)
            token_sort_ratio = fuzz.token_sort_ratio(query, title)
            best_score = max(similarity, partial_ratio, token_sort_ratio)
            if best_score > 50:
                video = next(v for v in all_videos if v.id == video_id)
                videos.append(video)
        
        series_titles = [(s.id, s.title.lower()) for s in all_series]
        for series_id, title in series_titles:
            similarity = fuzz.ratio(query, title)
            partial_ratio = fuzz.partial_ratio(query, title)
            token_sort_ratio = fuzz.token_sort_ratio(query, title)
            best_score = max(similarity, partial_ratio, token_sort_ratio)
            if best_score > 50:
                series = next(s for s in all_series if s.id == series_id)
                series_list.append(series)
    
    return render_template('search_results.html', videos=videos, series=series_list, query=request.args.get('query', ''))

# ===== PASSWORD RESET ROUTES =====

@app.route('/forgot', methods=['GET', 'POST'])
def forgot():
    if request.method == 'POST':
        email = request.form['email']
        user = User.query.filter_by(email=email).first()
        if user:
            token = get_token(email)
            link = url_for('reset', token=token, _external=True)
            msg = Message('Reset Password', recipients=[email])
            msg.body = f'Click: {link}'
            mail.send(msg)
            flash('Check your email', 'info')
            return redirect(url_for('login'))
    return """
    <!DOCTYPE html>
    <html>
    <body style="font-family:Arial; text-align:center; margin-top:100px;">
    <h2>Forgot Password</h2>
    <form method="post">
    <input type="email" name="email" placeholder="Your email" required><br><br>
    <button type="submit">Send Reset Link</button>
    </form>
    <br><a href="/login">Back</a>
    </body>
    </html>
    """

@app.route('/reset/<token>', methods=['GET', 'POST'])
def reset(token):
    email = verify_token(token)
    if not email:
        return 'Link invalid or expired. <a href="/forgot">Try again</a>'
    if request.method == 'POST':
        password = request.form['password']
        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        user = User.query.filter_by(email=email).first()
        if user:
            user.password = hashed
            db.session.commit()
            return 'Password updated! <a href="/login">Login now</a>'
        else:
            return 'User not found. <a href="/forgot">Try again</a>'
    return """
    <!DOCTYPE html>
    <html>
    <body style="font-family:Arial; text-align:center; margin-top:100px;">
    <h2>Create New Password</h2>
    <form method="post">
    <input type="password" name="password" placeholder="New password" required><br><br>
    <button type="submit">Reset Password</button>
    </form>
    </body>
    </html>
    """

# ===== RUN APP =====

if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=5000)  # ← FIXED: Added closing parenthesis
