#!/usr/bin/env python3
"""
Posts one queued clip to Instagram as a Reel, then records the result.

Reads queue.json, takes the first item with posted_at == null, hands Instagram
a public raw.githubusercontent URL for the video, waits for Instagram to finish
downloading and encoding it, publishes, and writes the outcome back to queue.json.

Needs one environment variable: IG_TOKEN
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request

API = "https://graph.instagram.com/v23.0"
QUEUE = "queue.json"

POLL_SECONDS = 20
POLL_ATTEMPTS = 18          # 18 x 20s = 6 minutes


def call(method, path, params):
    """Minimal Graph API call. Returns parsed JSON, raises on HTTP error body."""
    url = f"{API}{path}"
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        url = f"{url}?{data.decode()}"
        req = urllib.request.Request(url, method="GET")
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"{e.code} {body}") from None


def main():
    token = os.environ.get("IG_TOKEN")
    if not token:
        sys.exit("IG_TOKEN is not set. Add it as a repository secret.")

    q = json.load(open(QUEUE))
    repo, branch = q["repo"], q["branch"]

    nxt = next((i for i in q["items"] if not i["posted_at"] and not i["error"]), None)
    if nxt is None:
        print("Queue is empty - nothing left to post.")
        return

    video_url = (
        f"https://raw.githubusercontent.com/{repo}/{branch}/"
        + urllib.parse.quote(nxt["file"])
    )
    print(f"Posting: {nxt['file']}")
    print(f"Source:  {video_url}")

    params = {"media_type": "REELS", "video_url": video_url, "access_token": token}
    if nxt.get("caption"):
        params["caption"] = nxt["caption"]

    try:
        container = call("POST", "/me/media", params)["id"]
    except RuntimeError as e:
        nxt["error"] = f"container: {e}"
        json.dump(q, open(QUEUE, "w"), indent=1)
        sys.exit(f"Could not create container: {e}")
    print(f"Container: {container}")

    status = None
    info = {}
    for attempt in range(POLL_ATTEMPTS):
        time.sleep(POLL_SECONDS)
        info = call("GET", f"/{container}",
                    {"fields": "status_code,status", "access_token": token})
        status = info.get("status_code")
        print(f"  [{attempt + 1}/{POLL_ATTEMPTS}] {status}")
        if status in ("FINISHED", "ERROR", "EXPIRED"):
            break

    if status != "FINISHED":
        detail = info.get("status", "")
        nxt["error"] = f"processing: {status} {detail}".strip()
        json.dump(q, open(QUEUE, "w"), indent=1)
        sys.exit(f"Video never finished processing: {status} {detail}")

    try:
        published = call("POST", "/me/media_publish",
                         {"creation_id": container, "access_token": token})
    except RuntimeError as e:
        nxt["error"] = f"publish: {e}"
        json.dump(q, open(QUEUE, "w"), indent=1)
        sys.exit(f"Could not publish: {e}")

    nxt["posted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    nxt["media_id"] = published.get("id")
    json.dump(q, open(QUEUE, "w"), indent=1)

    remaining = sum(1 for i in q["items"] if not i["posted_at"] and not i["error"])
    print(f"Published. Media ID {nxt['media_id']}. {remaining} clips left in the queue.")


if __name__ == "__main__":
    main()
