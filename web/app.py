from asgiref.wsgi import WsgiToAsgi
from flask import Flask


app = Flask(__name__)


@app.get("/")
def hello_world() -> str:
    return "Hello, world!"


asgi_app = WsgiToAsgi(app)
