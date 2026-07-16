
# NOTE:
# Replace this file with your existing one if desired.
# This version includes:
# - S3 upload
# - API Gateway request
# - Wikipedia enrichment
# - DynamoDB history (CelebrityHistory)

from flask import Flask, render_template, request
import boto3
import requests
import os
import time
import re
from werkzeug.utils import secure_filename
from config import AWS_REGION, BUCKET_NAME, API_URL

app = Flask(__name__)

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

s3 = boto3.client("s3", region_name=AWS_REGION)

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
history_table = dynamodb.Table("CelebrityHistory")


def get_celebrity_info_wikipedia(name):
    try:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{name.replace(' ','_')}"
        r = requests.get(url, headers={"User-Agent":"CelebVisionAI"}, timeout=5)
        if r.status_code == 200:
            d = r.json()
            desc = d.get("description","Celebrity")
            extract = d.get("extract","")
            born = "Unknown"
            m = re.search(r"born[^\d]{0,10}(\d{4})", extract, re.I)
            if m:
                born = m.group(1)
            return {
                "profession": desc.title(),
                "country": "Unknown",
                "born": born,
                "known_for": extract.split(".")[0] if extract else "Recognized by AWS Rekognition",
                "emoji": "⭐",
                "wiki_url": d.get("content_urls",{}).get("desktop",{}).get("page","")
            }
    except Exception:
        pass
    return {
        "profession":"Celebrity",
        "country":"Unknown",
        "born":"Unknown",
        "known_for":"Recognized by AWS Rekognition",
        "emoji":"⭐",
        "wiki_url":""
    }


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/detect", methods=["POST"])
def detect():
    try:
        start = time.time()

        if "image" not in request.files:
            return render_template("index.html", error="No image selected.")

        image = request.files["image"]

        if image.filename == "":
            return render_template("index.html", error="Please choose an image.")

        filename = secure_filename(image.filename)
        local_path = os.path.join(UPLOAD_FOLDER, filename)
        image.save(local_path)

        with open(local_path, "rb") as f:
            s3.upload_fileobj(
                f,
                BUCKET_NAME,
                filename,
                ExtraArgs={"ContentType": image.content_type}
            )

        api = requests.get(f"{API_URL}?image={filename}")
        result = api.json()

        celebrities = []

        for celeb in result.get("celebrities", []):
            info = get_celebrity_info_wikipedia(celeb["name"])
            celebrities.append({
                "name": celeb["name"],
                "confidence": celeb["confidence"],
                **info
            })

        processing_time = round(time.time() - start, 2)

        return render_template(
            "index.html",
            celebrities=celebrities,
            image_url="/" + local_path.replace("\\", "/"),
            processing_time=processing_time,
            total_found=len(celebrities)
        )

    except Exception as e:
        return render_template("index.html", error=str(e))


@app.route("/history")
def history():
    try:
        response = history_table.scan()

        records = []

        for item in response.get("Items", []):

            for celeb in item.get("celebrities", []):
                records.append({
                    "request_id": item.get("request_id"),
                    "image": item.get("image_name"),
                    "name": celeb.get("name"),
                    "confidence": float(celeb.get("confidence")),
                    "timestamp": item.get("timestamp")
                })

        records.sort(key=lambda x: x["timestamp"], reverse=True)

        return render_template("history.html", records=records)

    except Exception as e:
        return render_template("history.html", error=str(e), records=[])


@app.route("/about")
def about():
    return render_template("about.html")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
