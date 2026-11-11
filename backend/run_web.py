import os
import secrets
from app import create_app

if __name__ == "__main__":
    if not os.environ.get("SECRET_KEY"):
        print("Development only: generating a temporary SECRET_KEY. Set SECRET_KEY for persistent sessions.")
        os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
    app = create_app()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
