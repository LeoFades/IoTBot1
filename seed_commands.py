from app import create_app, db
from app.models import Command

app = create_app()

with app.app_context():
    default_commands = ['move_forward', 'move_backward', 'turn_left', 'turn_right', 'speak']
    for cmd_name in default_commands:
        existing = Command.query.filter_by(action=cmd_name).first()
        if not existing:
            new_cmd = Command(action=cmd_name, active=False)
            db.session.add(new_cmd)
    db.session.commit()
    print("Command rows seeded.")
