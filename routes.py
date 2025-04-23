from flask import render_template, request, redirect, url_for, flash, session
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import json
from models import db, Customer, Product, Order, Review
from utils import allowed_file, client, save_image, delete_image

def init_routes(app):
    @app.before_request
    def ensure_cart():
        session.setdefault('cart', {})  # Changed to dict to store quantities

    @app.route('/')
    def index():
        # Get search and filter parameters
        search_query = request.args.get('q', '').strip()
        min_price = request.args.get('min_price', type=float)
        max_price = request.args.get('max_price', type=float)
        sort = request.args.get('sort', 'newest')
        
        # Start with base query
        query = Product.query
        
        # Apply search if provided
        if search_query:
            # Split search terms and search in both name and description
            search_terms = search_query.split()
            search_filters = []
            for term in search_terms:
                search_filters.append(
                    db.or_(
                        Product.name.ilike(f'%{term}%'),
                        Product.description.ilike(f'%{term}%')
                    )
                )
            query = query.filter(db.and_(*search_filters))
        
        # Apply price filters
        if min_price is not None:
            query = query.filter(Product.price >= min_price)
        if max_price is not None:
            query = query.filter(Product.price <= max_price)
        
        # Apply sorting
        if sort == 'newest':
            query = query.order_by(Product.created_at.desc())
        elif sort == 'price_low':
            query = query.order_by(Product.price.asc())
        elif sort == 'price_high':
            query = query.order_by(Product.price.desc())
        elif sort == 'name':
            query = query.order_by(Product.name.asc())
        elif sort == 'rating':
            # Subquery to calculate average rating
            avg_rating = db.session.query(
                Review.product_id,
                db.func.avg(Review.rating).label('avg_rating')
            ).group_by(Review.product_id).subquery()
            
            query = query.outerjoin(avg_rating, Product.id == avg_rating.c.product_id)\
                        .order_by(db.desc(avg_rating.c.avg_rating.nullslast()))
            
        # Get price range for filter UI
        price_range = db.session.query(
            db.func.min(Product.price),
            db.func.max(Product.price)
        ).first()
        
        products = query.all()
        return render_template('index.html',
                             products=products,
                             search_query=search_query,
                             min_price=min_price,
                             max_price=max_price,
                             sort=sort,
                             price_range=price_range)

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            name = request.form['name']
            email = request.form['email']
            password = request.form['password']
            
            if Customer.query.filter_by(email=email).first():
                flash("Email already registered.", "danger")
                return redirect(url_for('register'))
                
            hashed_pw = generate_password_hash(password)
            user = Customer(name=name, email=email, password=hashed_pw)
            db.session.add(user)
            db.session.commit()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for('login'))
        return render_template('register.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            email = request.form['email']
            password = request.form['password']
            user = Customer.query.filter_by(email=email).first()
            if user and check_password_hash(user.password, password):
                login_user(user)
                flash("Login successful!", "success")
                return redirect(url_for('index'))
            flash("Invalid credentials.", "danger")
        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        session.pop('cart', None)
        flash("You've been logged out.", "info")
        return redirect(url_for('login'))

    @app.route('/add_to_cart/<int:product_id>')
    @login_required
    def add_to_cart(product_id):
        cart = session.get('cart', {})
        cart[str(product_id)] = cart.get(str(product_id), 0) + 1
        session['cart'] = cart
        flash("Product added to cart!", "success")
        return redirect(request.referrer or url_for('index'))

    @app.route('/update_cart_quantity/<int:product_id>', methods=['POST'])
    @login_required
    def update_cart_quantity(product_id):
        cart = session.get('cart', {})
        quantity = int(request.form.get('quantity', 1))
        
        if quantity > 0 and quantity <= 99:
            cart[str(product_id)] = quantity
            session['cart'] = cart
            flash("Cart updated.", "success")
        else:
            flash("Invalid quantity. Please enter a number between 1 and 99.", "danger")
            
        return redirect(url_for('cart'))

    @app.route('/cart')
    @login_required
    def cart():
        cart_items = session.get('cart', {})
        products = []
        total = 0
        
        if cart_items:
            for product_id, quantity in cart_items.items():
                product = Product.query.get(int(product_id))
                if product:
                    subtotal = product.price * quantity
                    products.append({
                        'product': product,
                        'quantity': quantity,
                        'subtotal': subtotal
                    })
                    total += subtotal
                    
        return render_template("cart.html", cart_items=products, total=total)

    @app.route('/remove_from_cart/<int:product_id>')
    @login_required
    def remove_from_cart(product_id):
        cart = session.get('cart', {})
        cart.pop(str(product_id), None)
        session['cart'] = cart
        flash("Product removed from cart.", "info")
        return redirect(url_for('cart'))

    @app.route('/place_cart_order', methods=['POST'])
    @login_required
    def place_cart_order():
        cart_items = session.get('cart', {})
        if not cart_items:
            flash("Your cart is empty!", "warning")
            return redirect(url_for('cart'))

        name = request.form.get('name')
        email = request.form.get('email')
        address = request.form.get('address')

        if not all([name, email, address]):
            flash("Please fill in all shipping information.", "danger")
            return redirect(url_for('cart'))

        try:
            for product_id, quantity in cart_items.items():
                product = Product.query.get(int(product_id))
                if product:
                    order = Order(
                        customer_id=current_user.id,
                        product_id=product.id,
                        product_price=product.price,
                        quantity=quantity,
                        status='placed',
                        shipping_address=address
                    )
                    db.session.add(order)
            
            db.session.commit()
            session['cart'] = {}
            flash("Order placed successfully!", "success")
            return redirect(url_for('orders'))
            
        except Exception as e:
            db.session.rollback()
            flash("Error placing order. Please try again.", "danger")
            return redirect(url_for('cart'))

    @app.route('/orders')
    @login_required
    def orders():
        status = request.args.get('status')
        sort = request.args.get('sort', 'date_desc')
        
        # Start with base query
        query = Order.query.filter_by(customer_id=current_user.id)
        
        # Apply status filter if provided
        if status:
            query = query.filter_by(status=status)
        
        # Apply sorting
        if sort == 'date_asc':
            query = query.order_by(Order.placed_time.asc())
        elif sort == 'date_desc':
            query = query.order_by(Order.placed_time.desc())
        elif sort == 'price_asc':
            query = query.order_by(Order.product_price.asc())
        elif sort == 'price_desc':
            query = query.order_by(Order.product_price.desc())
            
        orders = query.all()
        return render_template("orders.html", orders=orders, status=status, sort=sort)

    @app.route('/cancel_order/<int:order_id>', methods=['POST'])
    @login_required
    def cancel_order(order_id):
        order = Order.query.get_or_404(order_id)
        
        # Verify order belongs to current user
        if order.customer_id != current_user.id:
            flash("You don't have permission to cancel this order.", "danger")
            return redirect(url_for('orders'))
        
        # Only allow cancellation of orders in 'placed' status
        if order.status != 'placed':
            flash("This order cannot be cancelled.", "danger")
            return redirect(url_for('orders'))
        
        order.status = 'cancelled'
        try:
            db.session.commit()
            flash("Order cancelled successfully.", "success")
        except:
            db.session.rollback()
            flash("Error cancelling order. Please try again.", "danger")
            
        return redirect(url_for('orders'))

    @app.route('/search_orders')
    @login_required
    def search_orders():
        date_str = request.args.get('date')
        orders = []
        if date_str:
            try:
                start_datetime = datetime.strptime(date_str, "%Y-%m-%d")
                end_datetime = start_datetime.replace(hour=23, minute=59, second=59)
                orders = Order.query.filter(
                    Order.placed_time >= start_datetime,
                    Order.placed_time <= end_datetime
                ).join(Product).options(db.joinedload(Order.product)).all()
            except ValueError:
                flash("Invalid date format. Use YYYY-MM-DD.", "danger")

        return render_template("search_orders.html", orders=orders, date_str=date_str, now=datetime.now())

    @app.route('/create_product', methods=['GET', 'POST'])
    @login_required
    def create_product():
        if request.method == 'POST':
            name = request.form.get('name')
            price = request.form.get('price')
            description = request.form.get('description')
            image_file = request.files.get('image')
            
            if not all([name, price, image_file]):
                flash("All fields except description are required", "danger")
                return redirect(url_for('create_product'))
            
            if not allowed_file(image_file.filename):
                flash(f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}", "danger")
                return redirect(url_for('create_product'))
                
            try:
                price = float(price)
                if price <= 0:
                    raise ValueError("Price must be greater than 0")
                
                # Process and save the image
                image_path = save_image(image_file, app.config['UPLOAD_FOLDER'])
                if not image_path:
                    flash("Error processing image. Please try again.", "danger")
                    return redirect(url_for('create_product'))
                
                product = Product(
                    name=name,
                    price=price,
                    description=description,
                    image=image_path
                )
                db.session.add(product)
                db.session.commit()
                flash("Product created successfully!", "success")
                return redirect(url_for('product_detail', product_id=product.id))
                
            except ValueError as e:
                flash(str(e) if str(e) else "Invalid price value", "danger")
            except Exception as e:
                db.session.rollback()
                if image_path:
                    delete_image(image_path, app.config['UPLOAD_FOLDER'])
                flash("Error creating product. Please try again.", "danger")
                
        return render_template('create_product.html')

    @app.route('/product/<int:product_id>')
    def product_detail(product_id):
        product = Product.query.get_or_404(product_id)
        return render_template('product_page.html', product=product)

    @app.route('/product/<int:product_id>/reviews')
    def product_reviews(product_id):
        product = Product.query.get_or_404(product_id)
        reviews = Review.query.filter_by(product_id=product.id).all()
        total_reviews = len(reviews)
        average_rating = round(sum([r.rating for r in reviews]) / total_reviews, 1) if total_reviews > 0 else 0

        # Count ratings by number
        rating_counts = {i: 0 for i in range(1, 6)}
        for r in reviews:
            rating_counts[r.rating] += 1

        can_review = False
        if current_user.is_authenticated:
            has_purchased = Order.query.filter_by(
                customer_id=current_user.id,
                product_id=product.id,
                status='delivered'
            ).first() is not None
            has_reviewed = Review.query.filter_by(
                customer_id=current_user.id,
                product_id=product.id
            ).first() is not None
            can_review = has_purchased and not has_reviewed

        return render_template(
            'reviews.html',
            product=product,
            reviews=reviews,
            total_reviews=total_reviews,
            average_rating=average_rating,
            rating_counts=rating_counts,
            can_review=can_review,
            sort_by=request.args.get("sort", "newest"),
            page=1,  # Placeholder for pagination
            pages=1  # Placeholder for pagination
        )


    @app.route('/product/<int:product_id>/review', methods=['POST'])
    @login_required
    def add_review(product_id):
        product = Product.query.get_or_404(product_id)
        
        # Verify user has purchased and received the product
        has_purchased = Order.query.filter_by(
            customer_id=current_user.id,
            product_id=product_id,
            status='delivered'
        ).first()
        
        if not has_purchased:
            flash("You can only review products you've purchased and received.", "warning")
            return redirect(url_for('product_reviews', product_id=product_id))
        
        # Check if user has already reviewed this product
        existing_review = Review.query.filter_by(
            customer_id=current_user.id,
            product_id=product_id
        ).first()
        
        if existing_review:
            flash("You've already reviewed this product.", "warning")
            return redirect(url_for('product_reviews', product_id=product_id))
        
        try:
            rating = int(request.form.get('rating'))
            if not 1 <= rating <= 5:
                raise ValueError("Invalid rating")
                
            comment = request.form.get('comment')
            if not comment or len(comment.strip()) == 0:
                flash("Review comment is required.", "danger")
                return redirect(url_for('product_reviews', product_id=product_id))
            
            review = Review(
                customer_id=current_user.id,
                product_id=product_id,
                rating=rating,
                comment=comment
            )
            db.session.add(review)
            db.session.commit()
            flash("Your review has been posted!", "success")
            
        except ValueError:
            flash("Please provide a valid rating (1-5 stars).", "danger")
        except Exception as e:
            db.session.rollback()
            flash("Error posting review. Please try again.", "danger")
            
        return redirect(url_for('product_reviews', product_id=product_id))

    @app.route('/review/<int:review_id>/delete', methods=['POST'])
    @login_required
    def delete_review(review_id):
        review = Review.query.get_or_404(review_id)
        
        if review.customer_id != current_user.id:
            flash("You don't have permission to delete this review.", "danger")
            return redirect(url_for('product_reviews', product_id=review.product_id))
        
        try:
            product_id = review.product_id
            db.session.delete(review)
            db.session.commit()
            flash("Your review has been deleted.", "success")
        except:
            db.session.rollback()
            flash("Error deleting review. Please try again.", "danger")
            
        return redirect(url_for('product_reviews', product_id=product_id))

    @app.route('/ask_together', methods=['POST'])
    def ask_together():
        user_query = request.form.get('query')
        prompt = f"""You are a shopping assistant. A user says: '{user_query}'.
    Suggest filters as JSON. Format: {{"keywords": [], "max_price": optional_number}}"""

        try:
            response = client.chat.completions.create(
                model="meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
                messages=[
                    {"role": "system", "content": "You're a helpful e-commerce assistant."},
                    {"role": "user", "content": prompt}
                ]
            )
            filters = json.loads(response.choices[0].message.content.strip())

            query = Product.query
            if 'keywords' in filters and filters['keywords']:
                for kw in filters['keywords']:
                    query = query.filter(Product.name.ilike(f"%{kw}%"))
            if 'max_price' in filters and filters['max_price']:
                query = query.filter(Product.price <= filters['max_price'])

            products = query.all()
            return render_template("index.html", products=products)

        except Exception as e:
            flash("Could not understand your query. Please try again.", "danger")
            return redirect(url_for('index'))

    @app.route('/chat_gpt', methods=['POST'])
    def chat_gpt():
        user_message = request.json.get('message')

        try:
            # First, extract product-related keywords
            keyword_response = client.chat.completions.create(
                model="meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
                messages=[
                    {"role": "system", "content": "Extract product-related keywords from user queries."},
                    {"role": "user", "content": f"Extract keywords from: {user_message}"}
                ]
            )
            keywords = json.loads(keyword_response.choices[0].message.content.strip())

            # Search for matching products
            query = Product.query
            for kw in keywords:
                query = query.filter(Product.name.ilike(f"%{kw}%"))
            products = query.limit(5).all()

            if not products:
                return {"reply": "I couldn't find any matching products. Can you try describing what you're looking for differently?"}

            # Format product suggestions
            product_list = []
            for p in products:
                product_list.append({
                    "name": p.name,
                    "price": p.price,
                    "image": url_for('static', filename=p.image, _external=True),
                    "url": url_for('product_detail', product_id=p.id, _external=True)
                })

            # Generate final response
            final_response = client.chat.completions.create(
                model="meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
                messages=[
                    {"role": "system", "content": "You're a helpful shopping assistant"},
                    {"role": "user", "content": f"Generate a friendly response for: {user_message}\nInclude these products: {json.dumps(product_list)}"}
                ]
            )
            reply = final_response.choices[0].message.content.strip()
            return {"reply": reply, "products": product_list}

        except Exception as e:
            return {"reply": "Sorry, I'm having trouble processing your request. Please try again."}, 500

    @app.route('/profile')
    @login_required
    def profile():
        total_orders = Order.query.filter_by(customer_id=current_user.id).count()
        total_reviews = Review.query.filter_by(customer_id=current_user.id).count()
        
        # Get recent orders
        recent_orders = Order.query.filter_by(customer_id=current_user.id)\
            .order_by(Order.placed_time.desc())\
            .limit(5)\
            .all()
            
        # Get recent reviews
        recent_reviews = Review.query.filter_by(customer_id=current_user.id)\
            .order_by(Review.created_at.desc())\
            .limit(5)\
            .all()
            
        return render_template('profile.html',
                             total_orders=total_orders,
                             total_reviews=total_reviews,
                             recent_orders=recent_orders,
                             recent_reviews=recent_reviews,
                             order_type=Order)

    @app.route('/update_profile', methods=['POST'])
    @login_required
    def update_profile():
        name = request.form.get('name')
        email = request.form.get('email')
        
        if not name or not email:
            flash("Name and email are required.", "danger")
            return redirect(url_for('profile'))
        
        # Check if email is already taken by another user
        existing_user = Customer.query.filter(
            Customer.email == email,
            Customer.id != current_user.id
        ).first()
        
        if existing_user:
            flash("Email address is already in use.", "danger")
            return redirect(url_for('profile'))
        
        try:
            current_user.name = name
            current_user.email = email
            db.session.commit()
            flash("Profile updated successfully!", "success")
        except:
            db.session.rollback()
            flash("Error updating profile. Please try again.", "danger")
            
        return redirect(url_for('profile'))

    @app.route('/change_password', methods=['POST'])
    @login_required
    def change_password():
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not all([current_password, new_password, confirm_password]):
            flash("All password fields are required.", "danger")
            return redirect(url_for('profile'))
            
        if not check_password_hash(current_user.password, current_password):
            flash("Current password is incorrect.", "danger")
            return redirect(url_for('profile'))
            
        if new_password != confirm_password:
            flash("New passwords don't match.", "danger")
            return redirect(url_for('profile'))
            
        # Validate password complexity
        if len(new_password) < 8 or not any(c.isalpha() for c in new_password) or not any(c.isdigit() for c in new_password):
            flash("Password must be at least 8 characters long and include both letters and numbers.", "danger")
            return redirect(url_for('profile'))
        
        try:
            current_user.password = generate_password_hash(new_password)
            db.session.commit()
            flash("Password changed successfully!", "success")
        except:
            db.session.rollback()
            flash("Error changing password. Please try again.", "danger")
            
        return redirect(url_for('profile'))