import os
import sqlite3
from flask import Flask, render_template,make_response, redirect, url_for, flash, request, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO, send
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from io import BytesIO
from functools import wraps


app = Flask(__name__)

# Konfiguracija baze podataka (primjer za SQLite)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///baza.db?timeout=60'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'tajna_kljuc'  # Za sesije i flash poruke

# Postavke za upload
UPLOAD_FOLDER = 'uploads/'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Inicijalizacija SQLAlchemy i Migrate
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# SocketIO setup
socketio = SocketIO(app)

# Model za korisnika (User)
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    address = db.Column(db.String(200), nullable=False)

    def __repr__(self):
        return f"User('{self.email}', '{self.first_name}', '{self.last_name}')"

# Model za proizvode (Product)
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(500), nullable=True)
    image = db.Column(db.String(200), nullable=True)
    category = db.Column(db.String(50), nullable=False, default='general') 
    
    def __repr__(self):
        return f"Product('{self.name}', '{self.price}', '{self.image}', '{self.category}')"

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    delivery_date = db.Column(db.String(100), nullable=False)  
    delivery_address = db.Column(db.String(200), nullable=False)  
    status = db.Column(db.String(50), default='pending')
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __repr__(self):
        return f"Order('{self.user_id}', '{self.total_price}', '{self.status}', '{self.delivery_date}')"


# Funkcija za provjeru prijave
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Morate biti prijavljeni kako biste dovršili narudžbu.', 'danger')
            return redirect(url_for('login'))  # Redirekcija na login stranicu
        return f(*args, **kwargs)
    return decorated_function

@app.route('/download_invoice')
@login_required
def download_invoice():
    # Dohvati ID narudžbe iz sesije
    order_id = session.get('last_order_id')
    if not order_id:
        flash('Nema dostupne narudžbe za preuzimanje računa.', 'danger')
        return redirect(url_for('shop'))

    # Dohvati narudžbu iz baze podataka
    order = Order.query.get_or_404(order_id)
    user = User.query.get_or_404(order.user_id)

    # Kreiraj PDF objekt u memoriji
    pdf_buffer = BytesIO()

    # Generiranje PDF-a koristeći ReportLab
    pdf_canvas = canvas.Canvas(pdf_buffer, pagesize=letter)
    
    # Dodaj informacije na PDF
    pdf_canvas.drawString(100, 750, "Invoice for your order")
    pdf_canvas.drawString(100, 730, f"Order ID: {order.id}")
    pdf_canvas.drawString(100, 710, f"Customer name: {user.first_name} {user.last_name}")
    pdf_canvas.drawString(100, 690, f"Delivery address: {order.delivery_address}")
    pdf_canvas.drawString(100, 670, f"Delivery date: {order.delivery_date}")
    pdf_canvas.drawString(100, 650, f"Total price: {order.total_price} €")
    
    # Završavanje PDF-a
    pdf_canvas.showPage()
    pdf_canvas.save()

    # Postavi pointer na početak
    pdf_buffer.seek(0)

    # Pošalji PDF kao response
    response = make_response(pdf_buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=invoice_order_{order.id}.pdf'
    
    return response



# Model za prilagođene narudžbe (Custom Order)
class CustomOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    image = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(50), default='pending')

    def __repr__(self):
        return f"CustomOrder('{self.user_id}', '{self.description}', '{self.status}')"



# Provjera ekstenzije datoteke
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Početna stranica
@app.route('/')
def home():
    user_first_name = session.get('user_first_name')
    return render_template('index.html', user_first_name=user_first_name)

# Stranica za shop
@app.route('/shop')
def shop():
    products = Product.query.all()
    return render_template('shop.html', products=products)

# Stranica za subscription (registraciju)
@app.route('/subscription', methods=['GET', 'POST'])
def subscription():
    if request.method == 'POST':
        try:
            first_name = request.form['first_name']
            last_name = request.form['last_name']
            address = request.form['address']
            email = request.form['email']
            password = request.form['password']
            hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

            # Provjera je li e-mail već registriran
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash('E-mail već postoji!', 'danger')
                return redirect(url_for('subscription'))
            
            # Spremanje korisnika u bazu podataka
            new_user = User(email=email, password=hashed_password, first_name=first_name, last_name=last_name, address=address)

            db.session.add(new_user)
            db.session.commit()

            session['user_first_name'] = new_user.first_name  # Postavljanje sesije s imenom
            flash('Registracija uspješna!', 'success')
            return redirect(url_for('home'))

        except Exception as e:
            db.session.rollback()
            error_message = f"Došlo je do pogreške prilikom registracije: {str(e)}"
            print(error_message)  # Ispisuje pogrešku u konzolu za lakšu dijagnostiku
            flash(error_message, 'danger')
            return redirect(url_for('subscription'))

    return render_template('subscription.html')



# Dodavanje novog proizvoda (admin)
@app.route('/admin/products/add', methods=['GET', 'POST'])
def add_product():
    if request.method == 'POST':
        name = request.form['name']
        price = request.form['price']
        description = request.form['description']
        image = request.form['image']
        category = request.form['category']  # Ovo je ključno za kategoriju

        # Provjeri je li kategorija ispravno dodana
        if category not in ['general', 'under_20', 'best_sellers', 'birthdays']:
            flash('Neispravna kategorija!', 'danger')
            return redirect(url_for('add_product'))

        # Spremanje proizvoda u bazu
        new_product = Product(name=name, price=price, description=description, image=image, category=category)
        db.session.add(new_product)
        db.session.commit()

        flash('Proizvod uspješno dodan!', 'success')
        return redirect(url_for('admin_products'))
    
    return render_template('add_product.html')



# Uređivanje proizvoda (admin)
@app.route('/admin/products/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        # Preuzmi podatke iz forme
        name = request.form.get('name')
        price = request.form.get('price')
        description = request.form.get('description')
        image = request.form.get('image')

        # Validacija
        if not name or not price:
            flash('Naziv i cijena proizvoda su obavezni!', 'danger')
            return redirect(url_for('edit_product', product_id=product_id))

        # Ažuriraj proizvod
        product.name = name
        product.price = price
        product.description = description
        product.image = image

        # Spremi promjene
        db.session.commit()
        flash('Proizvod uspješno ažuriran!', 'success')
        return redirect(url_for('admin_products'))

    return render_template('edit_product.html', product=product)

# Brisanje proizvoda (admin)
@app.route('/admin/products/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash('Proizvod uspješno izbrisan!', 'success')
    return redirect(url_for('admin_products'))



# Pregled proizvoda za admina
@app.route('/admin/products')
def admin_products():
    products = Product.query.all()  # Dohvati sve proizvode iz baze podataka
    return render_template('admin_products.html', products=products)

# Ruta za prikaz pojedinačnih proizvoda u shopu
@app.route('/product/<int:product_id>')
def product_details(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template('product_details.html', product=product)

# Ruta za upload prilagođenih buketa s opisom i slikom
@app.route('/upload_custom_bouquet', methods=['GET', 'POST'])
def upload_custom_bouquet():
    if request.method == 'POST':
        if 'image' not in request.files:
            flash('Nema učitane slike!', 'danger')
            return redirect(url_for('help'))

        file = request.files['image']
        description = request.form['description']

        if file.filename == '':
            flash('Nema odabrane slike!', 'danger')
            return redirect(url_for('help'))

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            # Spremanje narudžbe u bazu
            user_id = session.get('user_id')
            if not user_id:
                flash('Morate biti prijavljeni da napravite narudžbu.', 'danger')
                return redirect(url_for('login'))

            new_order = CustomOrder(user_id=user_id, description=description, image=filename)
            db.session.add(new_order)
            db.session.commit()

            flash('Vaša narudžba je uspješno poslana!', 'success')
            return redirect(url_for('shop'))

    return render_template('custom_order.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['user_first_name'] = user.first_name
            flash('Prijava uspješna!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Neispravan e-mail ili lozinka!', 'danger')

    return render_template('login.html')




@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    try:
        # Provjera ima li stavki u košarici
        if 'cart' not in session or not session['cart']:
            flash("Košarica je prazna.", 'danger')
            return redirect(url_for('shop'))

        # Dohvati košaricu i ukupnu cijenu
        cart = session['cart']
        total_price = sum(item['price'] * item['quantity'] for item in cart)
        delivery_date = request.form.get('delivery_date')
        delivery_address = request.form.get('common_delivery_address')

        # Provjera datuma i adrese
        if not delivery_date or not delivery_address:
            flash('Morate unijeti datum i adresu isporuke.', 'danger')
            return redirect(url_for('cart'))

        # Dohvati korisnika
        user_id = session.get('user_id')
        if not user_id:
            flash('Morate biti prijavljeni da dovršite narudžbu.', 'danger')
            return redirect(url_for('login'))

        # Kreiraj narudžbu
        new_order = Order(
            user_id=user_id,
            total_price=total_price,
            delivery_date=delivery_date,
            delivery_address=delivery_address
        )

        # Dodaj narudžbu u bazu
        db.session.add(new_order)
        db.session.commit()

        # Spremi ID narudžbe u sesiju
        session['last_order_id'] = new_order.id

        # Počisti košaricu nakon narudžbe
        session.pop('cart', None)

        flash('Narudžba je uspješno dovršena!', 'success')
        return redirect(url_for('order_summary'))  # Preusmjeri na sažetak narudžbe

    except sqlite3.OperationalError as e:
        db.session.rollback()
        flash(f"Problem s bazom podataka: {str(e)}", 'danger')
        return redirect(url_for('cart'))

    except Exception as e:
        db.session.rollback()
        flash(f'Došlo je do neočekivane pogreške: {str(e)}', 'danger')
        return redirect(url_for('cart'))




@app.route('/order_summary')
@login_required
def order_summary():
    # Dohvati ID narudžbe iz sesije
    order_id = session.get('last_order_id')

    if not order_id:
        flash('Nema dostupne narudžbe za prikaz.', 'danger')
        return redirect(url_for('shop'))

    # Dohvati narudžbu iz baze podataka
    order = Order.query.get_or_404(order_id)

    # Prikaži sažetak narudžbe
    return render_template('order_summary.html', order=order)



def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = User.query.get(session['user_id'])
        if not user.is_admin:
            flash('Nemate dopuštenje za pristup ovoj stranici.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/add_to_cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)
    
    cart = session.get('cart', [])
    
    # Dohvati veličinu proizvoda iz forme
    selected_size = request.form.get('size', 'classic')  # Default vrijednost je 'classic'
    
    # Postavi cijenu na temelju odabrane veličine
    if selected_size == 'deluxe':
        price = round(product.price * 1.5, 2)  # Deluxe (+50%)
    elif selected_size == 'premium':
        price = round(product.price * 2, 2)  # Premium (+100%)
    else:
        price = product.price  # Classic

    # Provjeri postoji li već taj proizvod u košarici s istom veličinom
    for item in cart:
        if item['id'] == product.id and item['size'] == selected_size:
            flash(f"{product.name} ({selected_size}) is already in the cart.", "info")
            return redirect(url_for('cart'))
    
    # Dodaj proizvod u košaricu
    cart.append({
        'id': product.id,
        'name': product.name,
        'price': price,  # Dodana cijena na temelju veličine
        'size': selected_size,  # Spremi odabranu veličinu
        'quantity': 1,
        'delivery_date': None,
        'delivery_address': None
    })
    
    session['cart'] = cart
    
    flash(f"{product.name} ({selected_size}) added to cart!", "success")
    return redirect(url_for('product_details', product_id=product_id))



@app.route('/update_cart', methods=['POST'])
def update_cart():
    cart = session.get('cart', [])

    # Prolazak kroz stavke u košarici i ažuriranje količine
    for item in cart:
        quantity_key = f'quantity_{item["id"]}'
        if quantity_key in request.form:
            new_quantity = int(request.form.get(quantity_key))
            item['quantity'] = new_quantity  # Ažuriraj količinu

    # Spremi ažuriranu košaricu
    session['cart'] = cart

    # Ponovno izračunaj ukupnu cijenu
    total_price = sum(item['price'] * item['quantity'] for item in cart)
    session['total_price'] = total_price

    flash('Košarica je ažurirana!', 'success')
    return redirect(url_for('cart'))



@app.route('/remove_from_cart/<int:product_id>')
def remove_from_cart(product_id):
    cart = session.get('cart', [])

    # Filtriraj košaricu i izbaci proizvod s odgovarajućim `product_id`
    cart = [item for item in cart if item['id'] != product_id]

    # Ažuriraj košaricu
    session['cart'] = cart

    flash('Product removed from cart.', 'success')
    return redirect(url_for('cart'))





# Stranica za odjavu (logout)
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user_first_name', None)
    flash('Odjava uspješna!', 'success')
    return redirect(url_for('home'))

# Stranica za help
@app.route('/help')
def help():
    return render_template('help.html')

# Live chat stranica
@app.route('/live_chat')
def live_chat():
    return render_template('live_chat.html')


@socketio.on('message')
def handle_message(msg):
    user_id = session.get('user_id', 'Guest')  # Identifikacija korisnika
    print(f"Message from {user_id}: {msg}")
    send(f"{user_id}: {msg}", broadcast=True)


@app.route('/under_20')
def under_20():
    products = Product.query.filter(Product.category == 'under_20').all()
    return render_template('under_20.html', products=products)

@app.route('/birthdays')
def birthdays():
    products = Product.query.filter_by(category="birthdays").all()
    return render_template('birthdays.html', products=products)


@app.route('/best_sellers')
def best_sellers():
    products = Product.query.filter_by(category="best_sellers").all()
    return render_template('best_sellers.html', products=products)

@app.route('/cart', methods=['GET', 'POST'])
def cart():
    cart = session.get('cart', [])
    
    if request.method == 'POST':
        # Ažuriraj količinu proizvoda na temelju unosa iz forme
        for item in cart:
            quantity_field = f'quantity_{item["id"]}'
            if quantity_field in request.form:
                item['quantity'] = int(request.form[quantity_field])
        
        # Ažuriraj košaricu u sesiji
        session['cart'] = cart

    # Izračunaj ukupnu cijenu uzimajući u obzir količinu
    total_price = sum(item['price'] * item.get('quantity', 1) for item in cart)
    
    session['total_price'] = total_price  # Spremi ukupnu cijenu u sesiju
    return render_template('cart.html', cart=cart, total_price=total_price)


if __name__ == '__main__':
    socketio.run(app, debug=True)

