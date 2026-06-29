# app.py
from flask import Flask, request, abort, send_from_directory
from linebot.v3.messaging import (
    MessagingApi,
    Configuration,
    ApiClient,
    TextMessage,
    ReplyMessageRequest,
    VideoMessage,
    ImageMessage,
    QuickReply,
    QuickReplyItem,
    PostbackAction,
    PushMessageRequest
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent, PostbackEvent
from linebot.v3.webhook import WebhookHandler

import json
import hmac
import hashlib
import os
import traceback
import random
from datetime import datetime

from fortune import get_fortune
from trend import extract_main_and_sub_related
from anime_search import handle_anime_search
from cataas import get_cat_video_url
from db import (
    init_db,
    save_image_from_line, 
    get_recent_photos, 
    like_photo, save_user, 
    get_all_users,
    delete_photo,
    delete_photo_by_number,
    get_photo_doc_id_by_public_id,
    get_user_like_counts,
    get_all_photo_docs
)

# -------------------- 初期化 --------------------
init_db()
app = Flask(__name__)

config = Configuration(access_token=os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))
ADMIN_USER_ID = os.environ.get("LINE_ADMIN_USER_ID")
CLOUDINARY_WEBHOOK_SECRET = os.environ.get("CLOUDINARY_WEBHOOK_SECRET")  # Cloudinary 署名キー

user_state = {}
anime_search_states = {}

# -------------------- テキストメッセージ --------------------
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    with ApiClient(config) as client:
        messaging_api = MessagingApi(client)
        reply_messages = []

        try:
            user_id = event.source.user_id
            user_msg = event.message.text.strip().lower()
            print(f"[RECEIVED] user_id: {user_id}, message: {user_msg}")
            
            save_user(user_id)

            # -------------------- 管理者専用コマンド: 写真削除 --------------------
            if user_id == ADMIN_USER_ID and user_msg.startswith("写真削除"):
                try:
                    # 「写真削除7」 → 数字部分だけ抜き出す
                    number_str = user_msg.replace("写真削除", "").strip()
                    number = int(number_str)

                    delete_photo_by_number(number)
                    reply_messages = [TextMessage(text=f"✅ Photo #{number} を削除しました")]
                except Exception as e:
                    print("[ERROR in delete command]", e)
                    reply_messages = [TextMessage(text="⚠️ 削除に失敗しました。番号を確認してください。")]

             # -------------------- 既存の処理（占いなど） --------------------
            elif user_msg in ["今日の占い", "うらない", "占い"]:
                result = get_fortune(user_id)
                reply_messages = [TextMessage(text=result)]

            elif user_msg == "流行検索":
                user_state[user_id] = "awaiting_keyword"
                reply_messages = [TextMessage(text="検索したい単語を入力してください（例：マック、新潟）")]

            elif user_state.get(user_id) == "awaiting_keyword":
                user_state[user_id] = None
                result = extract_main_and_sub_related(user_id, user_msg)
                reply_messages = [TextMessage(text=result)]

            elif user_msg == "アニメ検索":
                user_state[user_id] = "anime_search_waiting_for_title"
                anime_search_states[user_id] = {"titles": []}
                reply_messages = [TextMessage(text="好きなアニメを教えてください。複数入れてもOK。タイトルか「検索」と入力してください。")]

            elif user_state.get(user_id) == "anime_search_waiting_for_title":
                if user_msg == "検索":
                    result = handle_anime_search(user_id, user_msg, anime_search_states)
                    user_state[user_id] = None
                    reply_messages = [TextMessage(text=result)]
                else:
                    result = handle_anime_search(user_id, user_msg, anime_search_states)
                    reply_messages = [TextMessage(text=result)]

            elif user_msg in ["ねこ", "猫", "cat", "にゃー", "ニャー", "🐈"]:
                try:
                    cat_video_url, preview_image_url = get_cat_video_url(max_seconds=10)
                    reply_messages = [
                        VideoMessage(
                            original_content_url=cat_video_url,
                            preview_image_url=preview_image_url
                        )
                    ]
                except Exception as e:
                    print("[ERROR in cat video]", e)
                    reply_messages = [TextMessage(text="ごめん、猫動画の取得に失敗したよ…")]

            elif user_msg == "ランダム写真":
                photos = get_recent_photos(days=30)
                if not photos:
                    reply_messages = [TextMessage(text="まだ写真は保存されていません。")]
                else:
                    p = random.choice(photos)
                    image_url = p["image_url"]

                    reply_messages = [
                        ImageMessage(
                            original_content_url=image_url,
                            preview_image_url=image_url,
                            quick_reply=QuickReply(
                                items=[
                                    QuickReplyItem(
                                        action=PostbackAction(
                                            label="👍 いいね",
                                            data=f"like_photo:{p['id']}"
                                        )
                                    )
                                ]
                            )
                        )
                    ]

            else:
                reply_messages = [TextMessage(text=f"あなたが送ったメッセージ：{event.message.text}")]

            messaging_api.reply_message_with_http_info(
                ReplyMessageRequest(reply_token=event.reply_token, messages=reply_messages)
            )

        except Exception as e:
            print("[ERROR in handle_message]", e)
            print(traceback.format_exc())

# -------------------- 画像メッセージ --------------------
@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    with ApiClient(config) as client:
        messaging_api = MessagingApi(client)
        try:
            user_id = event.source.user_id
            message_id = event.message.id

            image_url, doc_id, photo_number = save_image_from_line(message_id, user_id)

            messaging_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="📸 写真を保存しました！")]
                )
            )

        except Exception as e:
            print("[ERROR in handle_image]", e)
            messaging_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="写真の保存に失敗しました…")]
                )
            )

# -------------------- いいね機能 --------------------
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data

    # 「いいね」ボタンのPostbackかチェック
    if data.startswith("like_photo:"):
        doc_id = data.split(":")[1]  # 写真のFirestoreドキュメントID
        user_id = event.source.user_id  # 押したユーザーのID

        # セッションIDを生成（1表示につき1回を保証するため）
        # UTC時刻を付加して、同じ写真でも再表示時には別セッションとして扱う
        session_id = f"{user_id}_{doc_id}_{datetime.utcnow().isoformat()}"

        try:
            # likes処理
            result = like_photo(doc_id, user_id, session_id)

            if result == "already_liked":
                # このセッションではすでにいいね済み
                reply_text = "👍 この表示ではすでにいいねしています！"
            elif result is False:
                # 写真が存在しない場合
                reply_text = "写真が見つかりませんでした。"
            else:
                # 更新後のいいね数を返す
                reply_text = f"👍 いいねしました！ 現在 {result} 件です。"

        except Exception as e:
            print("[ERROR in like_photo]", e)
            reply_text = "いいねの更新に失敗しました。"

        # LINEに返信
        with ApiClient(config) as client:
            messaging_api = MessagingApi(client)
            messaging_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )


# -------------------- Webhook --------------------
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    print("[DEBUG] Webhook called. Body length:", len(body))

    try:
        handler.handle(body, signature)
    except Exception as e:
        print("[ERROR] Webhook handle error:", e)
        traceback.print_exc()
        abort(400)

    return 'OK'


# -------------------- tmpアクセス機能 --------------------
@app.route("/tmp/<path:filename>")
def serve_tmp(filename):
    """ /tmp の中身をブラウザ経由でアクセス可能にする """
    tmp_dir = "/tmp/cat_videos"
    file_path = os.path.join(tmp_dir, filename)

    # セキュリティ・存在チェック
    if not os.path.isfile(file_path):
        return "File not found", 404

    return send_from_directory(tmp_dir, filename)

# -------------------- 毎朝機能 --------------------
@app.route("/cron", methods=["GET"])
def cron_job():
    with ApiClient(config) as client:
        messaging_api = MessagingApi(client)
        users = get_all_users()
        user_like_counts = get_user_like_counts()

        for user_id in users:
            try:
                # --- 1通目：占い＋お題＋いいね数まとめ ---
                fortune = get_fortune(user_id)
                total_likes = user_like_counts.get(user_id, 0)
                photo_theme = "#飯テロ #動物 #青"

                text = (
                    f"{fortune}\n\n"
                    f"📸 今月のお題：{photo_theme}\n"
                    f"📊 累計いいね：{total_likes}"
                )

                messaging_api.push_message_with_http_info(
                    PushMessageRequest(to=user_id, messages=[TextMessage(text=text)])
                )

                # --- 2通目：ランダム写真（必ず送信） ---
                photos = get_recent_photos(days=30)
                if photos:
                    p = random.choice(photos)
                    image_msg = ImageMessage(
                        original_content_url=p["image_url"],
                        preview_image_url=p["image_url"],
                        quick_reply=QuickReply(
                            items=[
                                QuickReplyItem(
                                    action=PostbackAction(
                                        label="👍 いいね",
                                        data=f"like_photo:{p['id']}"
                                    )
                                )
                            ]
                        )
                    )
                    messaging_api.push_message_with_http_info(
                        PushMessageRequest(to=user_id, messages=[image_msg])
                    )

            except Exception as e:
                print(f"[ERROR] cron_job failed for user {user_id}: {e}")
                import traceback
                traceback.print_exc()

    return "OK"
# -------------------- 画像→データベース連動削除 --------------------
@app.route("/cloudinary-webhook", methods=["POST"])
def cloudinary_webhook():
    # 生のバイト列を取得
    body = request.get_data()
    print("[DEBUG] Webhook body bytes:", body)

    # JSON 解析
    try:
        data = json.loads(body)
        print("[DEBUG] Webhook JSON:", data)
    except Exception as e:
        print("[ERROR] Failed to parse JSON:", e)
        return "Bad JSON", 400

    # 署名チェックはなし（Cloudinary 最新 UI では Secret Key がない場合対応）
    # if CLOUDINARY_WEBHOOK_SECRET:
    #     ...署名チェック...

    # 削除イベントのみ処理
    if data.get("notification_type") == "delete":
        resources = data.get("resources", [])
        if not resources:
            print("[INFO] No resources found in delete event")
            return "OK"

        for resource in resources:
            public_id = resource.get("public_id")
            if not public_id:
                continue

            print(f"[INFO] Delete event received for public_id: {public_id}")

            # Firestore の doc_id を取得
            doc_id = get_photo_doc_id_by_public_id(public_id)
            if doc_id:
                try:
                    delete_photo(doc_id)
                    print(f"[INFO] Firestore doc {doc_id} deleted successfully.")
                except Exception as e:
                    print(f"[ERROR] Failed to delete Firestore doc {doc_id}:", e)
            else:
                print(f"[INFO] No Firestore doc found for public_id: {public_id}")

    return "OK"


# -------------------- ヘルスチェック（Cloudinary と Firebase 突合削除） --------------------
@app.route("/health", methods=["GET"])
def health():
    try:
        print("[HEALTH] Starting health check and cleanup...")

        # --- Cloudinary API から画像一覧取得 ---
        import cloudinary.api
        cloudinary_resources = cloudinary.api.resources(
            type="upload",
            max_results=500  # 必要ならページネーション対応
        )
        cloudinary_public_ids = {res['public_id'] for res in cloudinary_resources.get('resources', [])}
        print(f"[HEALTH] Cloudinary public IDs count: {len(cloudinary_public_ids)}")

        # --- Firebase から画像一覧取得 ---
        from db import get_all_photo_docs
        photo_docs = get_all_photo_docs()  # Firestore の全写真データ取得
        deleted_docs = []

        for doc in photo_docs:
            public_id = doc.get("public_id")
            doc_id = doc.get("id")
            if public_id and public_id not in cloudinary_public_ids:
                # Cloudinaryに存在しない場合は削除
                from db import delete_photo
                delete_photo(doc_id)
                deleted_docs.append(doc_id)
                print(f"[HEALTH] Deleted Firestore doc: {doc_id}")

        print(f"[HEALTH] Deleted {len(deleted_docs)} Firestore docs.")

        return f"OK — Deleted {len(deleted_docs)} docs", 200

    except Exception as e:
        print(f"[ERROR] Health check failed: {e}")
        import traceback
        traceback.print_exc()
        return "Error", 500
# -------------------- 起動 --------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
