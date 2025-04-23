import os
from dotenv import load_dotenv
import together
from PIL import Image
from werkzeug.utils import secure_filename
import uuid

load_dotenv()

# Initialize Together AI client
client = together.Together(api_key=os.getenv("TOGETHER_API_KEY"))

# File upload configurations
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_IMAGE_SIZE = (800, 800)  # Maximum dimensions for uploaded images

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_image(image_file, upload_folder):
    """
    Save and process an uploaded image file.
    - Generates a unique filename
    - Resizes the image if needed
    - Preserves aspect ratio
    - Optimizes file size
    """
    if not image_file:
        return None

    # Generate unique filename
    original_filename = secure_filename(image_file.filename)
    extension = original_filename.rsplit('.', 1)[1].lower()
    unique_filename = f"{uuid.uuid4().hex}.{extension}"
    
    # Create full path
    filepath = os.path.join(upload_folder, unique_filename)
    
    try:
        # Open and process image
        img = Image.open(image_file)
        
        # Convert RGBA to RGB if needed
        if img.mode == 'RGBA':
            bg = Image.new('RGB', img.size, 'WHITE')
            bg.paste(img, mask=img.split()[3])
            img = bg
        
        # Resize if image is too large
        if img.size[0] > MAX_IMAGE_SIZE[0] or img.size[1] > MAX_IMAGE_SIZE[1]:
            img.thumbnail(MAX_IMAGE_SIZE, Image.Resampling.LANCZOS)
        
        # Save optimized image
        img.save(filepath, optimize=True, quality=85)
        
        return f"images/{unique_filename}"
    except Exception as e:
        print(f"Error processing image: {e}")
        return None

def delete_image(image_path, upload_folder):
    """Delete an image file from the upload folder"""
    if not image_path:
        return False
    
    try:
        full_path = os.path.join(upload_folder, image_path.replace('images/', ''))
        if os.path.exists(full_path):
            os.remove(full_path)
            return True
    except Exception as e:
        print(f"Error deleting image: {e}")
    return False

# Application configuration
class Config:
    SQLALCHEMY_DATABASE_URI = 'sqlite:///ecommerce.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-change-it')  # Should be set in .env
    UPLOAD_FOLDER = os.path.join('static', 'images')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size


from models import db, Product, Review
from sqlalchemy import func, desc, case

def get_products_ordered_by_rating():
    """Return products ordered by average rating, with unrated products last."""
    subquery = (
        db.session.query(
            Review.product_id,
            func.avg(Review.rating).label('avg_rating')
        )
        .group_by(Review.product_id)
        .subquery()
    )

    products = (
        db.session.query(Product)
        .outerjoin(subquery, Product.id == subquery.c.product_id)
        .order_by(
            case(
                (subquery.c.avg_rating == None, 1),
                else_=0
            ),
            desc(subquery.c.avg_rating)
        )
        .all()
    )

    return products
