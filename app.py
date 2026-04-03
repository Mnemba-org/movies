from flask import Flask, render_template, redirect, url_for, request, flash, current_app
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from functools import wraps
import os
import uuid
import shutil
from fuzzywuzzy import fuzz, process
from models import Subscription, db, User, Video, Series, Episode
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for
from fuzzywuzzy import fuzz
import boto3
from botocore.config import Config
from flask_migrate import Migrate
from werkzeug.utils import secure_filename

# -------------------- Flask App Setup --------------------
app = Flask(__name__, template_folder='templates')
app.config['SECRET_KEY'] = 'your_secret_key_here'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('mydb')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mkv', 'mov', 'jpg', 'jpeg', 'png', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

app.config['R2_ACCESS_KEY'] = os.environ.get('R2_ACCESS_KEY')
app.config['R2_SECRET_KEY'] = os.environ.get('R2_SECRET_KEY')
app.config['R2_BUCKET'] = os.environ.get('R2_BUCKET')
app.config['R2_ENDPOINT'] = os.environ.get('R2_ENDPOINT')
app.config['R2_PUBLIC_URL'] = os.environ.get('R2_PUBLIC_URL')


db.init_app(app)


bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

with app.app_context():
    db.create_all()
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'series'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'thumbnails'), exist_ok=True)
    
def delete_from_r2(object_key):
    """Delete a file from R2 bucket"""
    try:
        s3_client = get_r2_client()
        s3_client.delete_object(
            Bucket=app.config['R2_BUCKET'],
            Key=object_key
        )
        print(f"Deleted from R2: {object_key}")
        return True
    except Exception as e:
        print(f"Error deleting from R2: {e}")
        return False

# -------------------- Helper Functions --------------------
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
        '.mp4': 'video/mp4',
        '.avi': 'video/x-msvideo',
        '.mkv': 'video/x-matroska',
        '.mov': 'video/quicktime',
        '.webm': 'video/webm',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif'
    }
    return content_types.get(ext, 'application/octet-stream')


def upload_to_r2(file_data, filename, folder='videos'):
    """
    Upload file to R2 bucket
    Returns: public URL of uploaded file
    """
    try:
        s3_client = get_r2_client()
        
        # Create the full object key (path in bucket)
        object_key = f"{folder}/{filename}"
        
        # Upload file to R2
        s3_client.upload_fileobj(
            file_data,
            app.config['R2_BUCKET'],
            object_key,
            ExtraArgs={
                'ContentType': get_content_type(filename),
                'ACL': 'public-read'
            }
        )
        
        # Return the public URL
        return f"{app.config['R2_PUBLIC_URL']}/{object_key}"
    
    except Exception as e:
        print(f"Error uploading to R2: {e}")
        return None

@app.route('/forgot-password', methods=['POST'])
def forgot_password():
    email = request.json.get('email')
    user = User.query.filter_by(email=email).first()
    
    if user:
        # Generate token
        token = secrets.token_urlsafe(32)
        user.reset_token = token
        user.reset_expires = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()
        
        # Send email (simplified)
        reset_link = f"http://localhost:5000/reset-password/{token}"
        # Send email with reset_link (use your email method)
    
    return jsonify({'message': 'Check your email for reset link'})


@app.route('/reset-password/<token>', methods=['POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    
    if not user or user.reset_expires < datetime.utcnow():
        return jsonify({'error': 'Invalid or expired token'}), 400
    
    new_password = request.json.get('password')
    user.password = bcrypt.generate_password_hash(new_password)
    user.reset_token = None
    user.reset_expires = None
    db.session.commit()
    
    return jsonify({'message': 'Password reset successful'})
    

def delete_from_r2(object_key):
    """Delete a file from R2 bucket"""
    try:
        s3_client = get_r2_client()
        s3_client.delete_object(
            Bucket=app.config['R2_BUCKET'],
            Key=object_key
        )
        return True
    except Exception as e:
        print(f"Error deleting from R2: {e}")
        return False


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

        # Plan duration
        if plan == "weekly":
            duration = timedelta(days=7)
        else:
            duration = timedelta(days=30)

        # Check existing active subscription
        existing = Subscription.query.filter(
            Subscription.user_id == user.id,
            Subscription.end_date > now
        ).first()

        if existing:
            # ✅ EXTEND TIME
            existing.end_date += duration
        else:
            # ✅ CREATE NEW
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

# -------------------- User Management --------------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
@app.context_processor
def inject_datetime():
    return dict(datetime=datetime)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        existing_user = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()

        if existing_user:
            if existing_user.username == username:
                flash('Username already exists!', 'error')
            else:
                flash('Email already registered!', 'error')
            return render_template('signup.html', error="Username or Email already exists")

        try:
            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
            new_user = User(username=username, email=email, password=hashed_password)
            db.session.add(new_user)
            db.session.commit()
            flash('Account created successfully!', 'success')
            return redirect(url_for('login'))
        except IntegrityError:
            db.session.rollback()
            flash('Registration failed. Please try again.', 'error')
            return redirect(url_for('signup'))

    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('home'))
        else:
            return render_template('login.html', error="Invalid email or password")
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))




# -------------------- Frontend Routes --------------------
@app.route('/')
def home():
    videos = Video.query.all()
    series_list = Series.query.all()
    
    return render_template('home.html', videos=videos, series_list=series_list)


# -------------------- Frontend Routes --------------------
@app.route('/time_left')
@login_required
def days_left():
    videos = Video.query.all()
    
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
        return redirect(url_for('subscribe'))

    return render_template('series.html', series=series, episodes=episodes)
@app.route('/subscribe')
@login_required
def subscribe():
    return '<a href="https://www.youtube.com" target="_blank"><button>Click here</button></a>'

@app.route('/my_subscription')
@login_required
def my_subscription():
    sub = get_active_subscription(current_user.id)
    return render_template('my_subscription.html', subscription=sub)
# -------------------- Admin Routes --------------------
@app.route('/admin_dashboard')
@login_required
@admin_required
def admin_dashboard():
    videos = Video.query.all()
    return render_template('aploadvideos.html', videos=videos)

@app.route('/upload', methods=['GET', 'POST'])
@admin_required
def post():  
    if request.method == 'POST':
        title = request.form['title']
        video = request.files['video']
        image = request.files['thumbnail']
        
        if not video or not image:
            flash('Please upload both video and thumbnail', 'error')
            return redirect(request.url)
        
        # Check if files are allowed
        if not allowed_file(video.filename) or not allowed_file(image.filename):
            flash('File type not allowed', 'error')
            return redirect(request.url)
        
        # Generate unique filenames
        video_filename = str(uuid.uuid4()) + os.path.splitext(video.filename)[1]
        image_filename = str(uuid.uuid4()) + os.path.splitext(image.filename)[1]
        
        # Upload to R2
        video_url = upload_to_r2(video, video_filename, 'videos')
        if not video_url:
            flash('Error uploading video to cloud storage', 'error')
            return redirect(request.url)
        
        thumbnail_url = upload_to_r2(image, image_filename, 'thumbnails')
        if not thumbnail_url:
            flash('Error uploading thumbnail to cloud storage', 'error')
            return redirect(request.url)
        
        free = 'free' in request.form
        
        # Save to database
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
@app.route('/add_series', methods=['GET', 'POST'])
@admin_required
def add_series():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form.get('description', '')
        thumbnail = request.files.get('thumbnail')
        
        thumbnail_url = None
        
        # Upload thumbnail to R2 if provided
        if thumbnail and thumbnail.filename and allowed_file(thumbnail.filename):
            thumbnail_filename = str(uuid.uuid4()) + os.path.splitext(thumbnail.filename)[1]
            # FIXED: Added 'series_covers' folder parameter
            thumbnail_url = upload_to_r2(thumbnail, thumbnail_filename, 'series_covers')
            if not thumbnail_url:
                flash('Error uploading thumbnail to cloud storage', 'error')
                return redirect(request.url)
        
        free = 'free' in request.form
        
        # Create new series
        new_series = Series(
            title=title,
            description=description,
            thumbnail=thumbnail_url,
            free=free
        )
        db.session.add(new_series)
        db.session.commit()
        
        flash(f'Series "{title}" added successfully!', 'success')
        # FIXED: Redirect to add_episodes with the new series ID
        return redirect(url_for('add_episodes', series_id=new_series.id))
    
    # FIXED: For GET request, pass series_list or remove series variable
    return render_template('add_series.html')

@app.route('/add_episodes/<int:series_id>/', methods=['GET', 'POST'])
@admin_required
def add_episodes(series_id):
    series = Series.query.get_or_404(series_id)
    
    # Create folder name for this series in R2
    folder_name = secure_filename(series.title.replace(' ', '_').lower())
    series_folder = f"series/{folder_name}"
    
    if request.method == 'POST':
        episode_title = request.form['title']
        episode_number = request.form['episode_number']
        video_file = request.files['video']
        video_url = None
        
        if video_file and video_file.filename:
            # Check if file extension is allowed
            if allowed_file(video_file.filename):
                video_filename = f"ep{episode_number}_{secure_filename(video_file.filename)}"
                
                # Upload to R2
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
        
        # Save to database with R2 URL
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
@admin_required
def delete_video(id):
    video = Video.query.get_or_404(id)
    
    # Delete video file from R2
    if video.video_path and app.config['R2_PUBLIC_URL'] in video.video_path:
        object_key = video.video_path.replace(f"{app.config['R2_PUBLIC_URL']}/", "")
        delete_from_r2(object_key)
    
    # Delete thumbnail from R2
    if video.thumbnail and app.config['R2_PUBLIC_URL'] in video.thumbnail:
        object_key = video.thumbnail.replace(f"{app.config['R2_PUBLIC_URL']}/", "")
        delete_from_r2(object_key)
    
    # Delete from database
    db.session.delete(video)
    db.session.commit()
    
    flash('Video deleted successfully from cloud storage!', 'success')
    return redirect(url_for('admin_dashboard'))

# -------------------- Series Management --------------------
@app.route('/index')
@admin_required
def index():
    series_list = Series.query.all()
    return render_template('index.html', series_list=series_list)


   





@app.route('/series/<int:series_id>')

def view_series(series_id):
    series = Series.query.get_or_404(series_id)
    episodes = Episode.query.filter_by(series_id=series_id).order_by(Episode.episode_number).all()
    return render_template('view_series.html', series=series, episodes=episodes)




@app.route('/search')
def search():
    query = request.args.get('query', '').lower().strip()
    
    if not query:
        return redirect(url_for('home'))
    
    # Get all videos and series
    all_videos = Video.query.all()
    all_series = Series.query.all()
    
    # Try exact matches first
    exact_videos = [v for v in all_videos if query in v.title.lower()]
    exact_series = [s for s in all_series if query in s.title.lower()]
    
    videos = []
    series_list = []
    
    if exact_videos or exact_series:
        videos = exact_videos
        series_list = exact_series
    else:
        # Fuzzy matching for videos
        video_titles = [(v.id, v.title.lower()) for v in all_videos]
        for video_id, title in video_titles:
            # Calculate similarity ratio
            similarity = fuzz.ratio(query, title)
            partial_ratio = fuzz.partial_ratio(query, title)
            token_sort_ratio = fuzz.token_sort_ratio(query, title)
            
            # Use the best score
            best_score = max(similarity, partial_ratio, token_sort_ratio)
            
            # If score is above threshold (50%), include it
            if best_score > 50:
                video = next(v for v in all_videos if v.id == video_id)
                videos.append(video)
        
        # Fuzzy matching for series
        series_titles = [(s.id, s.title.lower()) for s in all_series]
        for series_id, title in series_titles:
            similarity = fuzz.ratio(query, title)
            partial_ratio = fuzz.partial_ratio(query, title)
            token_sort_ratio = fuzz.token_sort_ratio(query, title)
            
            best_score = max(similarity, partial_ratio, token_sort_ratio)
            
            if best_score > 50:
                series = next(s for s in all_series if s.id == series_id)
                series_list.append(series)
        
        # Sort by relevance (highest similarity first)
        if videos:
            videos.sort(key=lambda v: max(
                fuzz.ratio(query, v.title.lower()),
                fuzz.partial_ratio(query, v.title.lower()),
                fuzz.token_sort_ratio(query, v.title.lower())
            ), reverse=True)
        
        if series_list:
            series_list.sort(key=lambda s: max(
                fuzz.ratio(query, s.title.lower()),
                fuzz.partial_ratio(query, s.title.lower()),
                fuzz.token_sort_ratio(query, s.title.lower())
            ), reverse=True)
    
    return render_template('search_results.html', 
                         query=query, 
                         videos=videos, 
                         series_list=series_list,
                         exact_matches=bool(exact_videos or exact_series))

@app.route('/delete_episode/<int:episode_id>', methods=['POST'])
@admin_required
def delete_episode(episode_id):
    episode = Episode.query.get_or_404(episode_id)
    series_id = episode.series_id
    
    # Delete video file from R2
    if episode.video_path and app.config['R2_PUBLIC_URL'] in episode.video_path:
        object_key = episode.video_path.replace(f"{app.config['R2_PUBLIC_URL']}/", "")
        delete_from_r2(object_key)
    
    # Delete from database
    db.session.delete(episode)
    db.session.commit()
    
    flash('Episode deleted successfully from cloud storage!', 'success')
    return redirect(url_for('view_series', series_id=series_id))
    

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
    
@app.route('/delete_series/<int:series_id>', methods=['POST'])
@admin_required
def delete_series(series_id):
    series = Series.query.get_or_404(series_id)
    
    # Get all episodes for this series
    episodes = Episode.query.filter_by(series_id=series_id).all()
    
    # Delete all episode videos from R2
    for episode in episodes:
        if episode.video_path and app.config['R2_PUBLIC_URL'] in episode.video_path:
            object_key = episode.video_path.replace(f"{app.config['R2_PUBLIC_URL']}/", "")
            delete_from_r2(object_key)
        
        # Delete episode from database
        db.session.delete(episode)
    
    # CHANGE THIS LINE - 'cover_image' to 'thumbnail'
    if series.thumbnail and app.config['R2_PUBLIC_URL'] in series.thumbnail:
        object_key = series.thumbnail.replace(f"{app.config['R2_PUBLIC_URL']}/", "")
        delete_from_r2(object_key)
    
    # Delete series folder from R2
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
    
    # Delete series from database
    db.session.delete(series)
    db.session.commit()
    
    flash('Series and all episodes deleted successfully from cloud storage!', 'success')
    return redirect(url_for('index'))

@app.route('/single_movies')
def single_movies():
    videos = Video.query.all()
    return render_template('choose_single.html',videos=videos)
@app.route('/choose_series')
def choose_series():
    series_list = Series.query.all()
    return render_template('choose_series.html', series_list=series_list)



@app.route('/video/<int:video_id>')
@login_required
def movie(video_id):
    video = Video.query.get_or_404(video_id)
    
    if not video.free and not has_access(current_user.id):
        return redirect(url_for('subscribe'))
    return render_template('watch_movie.html', video=video)
# -------------------- Run App --------------------
if __name__ == "__main__":
 app.run(debug=False, host="0.0.0.0", port=5000)
