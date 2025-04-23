from flask import Flask, render_template
from flask_login import LoginManager
from models import db, Customer
from routes import init_routes
from utils import Config
import os
from werkzeug.middleware.proxy_fix import ProxyFix

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Security headers
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Content-Security-Policy'] = "default-src 'self' https:; img-src 'self' data: https:; script-src 'self' 'unsafe-inline' https:; style-src 'self' 'unsafe-inline' https:;"
        return response

    # Error handlers
    @app.errorhandler(404)
    def page_not_found(error):
        return render_template('errors/404.html', code=404, message="Page Not Found"), 404

    @app.errorhandler(500)
    def internal_server_error(error):
        db.session.rollback()  # Roll back db session in case of error
        return render_template('errors/500.html', code=500, message="Internal Server Error"), 500

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template('errors/403.html', code=403, message="Access Forbidden"), 403

    # Ensure upload directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Initialize database
    db.init_app(app)

    # Initialize Login Manager
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message_category = 'info'
    login_manager.needs_refresh_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        return Customer.query.get(int(user_id))

    # Add custom Jinja2 filters
    @app.template_filter('slice')
    def slice_list(value, limit):
        return value[:limit]

    # Initialize routes
    init_routes(app)

    # Create database tables
    with app.app_context():
        db.create_all()

    # Enable proxy fix for proper IP handling behind reverse proxy
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)