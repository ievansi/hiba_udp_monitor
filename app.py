from flask import Flask, jsonify, render_template

from csv_logger import CsvLogger
from data_store import DataStore
from hiba_receiver import HibaUdpReceiver, load_channel_config


def create_app() -> Flask:
    app = Flask(__name__)

    channels = load_channel_config("config.yaml")
    store = DataStore(history_limit=1000)
    logger = CsvLogger("logs/hiba_log.csv", channels)

    receiver = HibaUdpReceiver(
        host="0.0.0.0",
        port=5010,
        allowed_source_ip="192.168.0.150",
        channels=channels,
        store=store,
        logger=logger,
    )
    receiver.start()

    @app.route("/")
    def index():
        return render_template("index.html", channels=channels)

    @app.route("/api/latest")
    def api_latest():
        return jsonify(store.latest())

    @app.route("/api/status")
    def api_status():
        return jsonify(store.status())

    @app.route("/api/history")
    def api_history():
        return jsonify(store.history())

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
