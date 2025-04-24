from . import db
from datetime import datetime


class Device(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(10), default='off')


class Command(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(100), unique=True, nullable=False)
    active = db.Column(db.Boolean, default=False)
