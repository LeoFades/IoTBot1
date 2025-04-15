# models.py
from app import db  # make sure to import db from where you defined it

class Device(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(10), default='off')  # can be 'on' or 'off'

    def __repr__(self):
        return f"<Device {self.name}>"
