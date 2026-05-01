from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class LibraryItem(db.Model):
    __tablename__ = "library_items"

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(500), nullable=False)
    author = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=True)

    series = db.Column(db.String(500), nullable=True)
    series_index = db.Column(db.String(100), nullable=True)
    isbn = db.Column(db.String(100), nullable=True)
    publisher = db.Column(db.String(500), nullable=True)
    language = db.Column(db.String(100), nullable=True)

    file_path = db.Column(db.String(2000), nullable=False, unique=True)
    file_name = db.Column(db.String(500), nullable=False)
    extension = db.Column(db.String(50), nullable=False)

    media_type = db.Column(db.String(50), nullable=False)

    cover_path = db.Column(db.String(2000), nullable=True)
    size_bytes = db.Column(db.Integer, nullable=True)

    manual_metadata = db.Column(db.Boolean, default=False)
    want_read = db.Column(db.Boolean, default=False)
    cover_locked = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def size_text(self):
        if not self.size_bytes:
            return "0 MB"

        size_mb = self.size_bytes / 1024 / 1024

        if size_mb >= 1024:
            return f"{size_mb / 1024:.2f} GB"

        return f"{size_mb:.1f} MB"

    def short_description(self):
        if not self.description:
            return "Ingen synopsis hittades ännu. Klicka på Metadata för att lägga till en egen synopsis."

        text = " ".join(self.description.split())

        if len(text) > 450:
            return text[:450] + "..."

        return text
