from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Flask 정상 작동 중"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
