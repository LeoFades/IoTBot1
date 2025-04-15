from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

app = Flask(__name__)

# Replace with your actual database info
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://@localhost/localhost'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/command', methods=['POST'])
def send_command():
    data = request.json
    # Process the command (e.g., control LoveBot)
    return jsonify({"status": "success"})

if __name__ == '__main__':
    app.run(debug=True)