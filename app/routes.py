from flask import Blueprint, render_template, request, jsonify
from .models import Device
from .models import Command
from . import db

main = Blueprint('main', __name__)

@main.route('/')
def dashboard():
    commands = Command.query.all()
    return render_template('dashboard.html', commands=commands)



@main.route('/api/toggle-command', methods=['POST'])
def toggle_command():
    data = request.get_json()
    command = Command.query.get(data['id'])

    if command:
        command.active = not command.active
        db.session.commit()
        return jsonify({'status': 'success', 'active': command.active})
    else:
        return jsonify({'status': 'error', 'message': 'Command not found'}), 404