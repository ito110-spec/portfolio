import os
import json
import tempfile
from datetime import datetime, timedelta
import requests
import cloudinary
import cloudinary.uploader
import firebase_admin
from firebase_admin import credentials, firestore

# -------------------- Cloudinary 初期化 --------------------
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET")
)

# -------------------- Firebase 初期化 --------------------
def init_firebase():
    """
    ローカル用（ファイルパス）でも Render 用（環境変数に JSON 本文）でも動く初期化
    """
    cred_path_or_json = os.environ.get("FIREBASE_CREDENTIALS")

    if cred_path_or_json:
        # ファイルか JSON 本文か判定
        if os.path.exists(cred_path_or_json):
            # ファイルパスとして認識
            cred = credentials.Certificate(cred_path_or_json)
        else:
            # JSON 本文として認識 → 一時ファイルに書き出す
            with tempfile.NamedTemporaryFile(delete=False) as f:
                f.write(cred_path_or_json.encode())
                temp_path = f.name
            cred = credentials.Certificate(temp_path)
    else:
        # デフォルト：secrets/firebase_credentials.json
        default_path = os.path.join(os.path.dirname(__file__), "secrets/firebase_credentials.json")
        if not os.path.exists(default_path):
            raise FileNotFoundError(
                "Firebase credentials file not found. "
                "Set FIREBASE_CREDENTIALS env or place secrets/firebase_credentials.json"
            )
        cred = credentials.Certificate(default_path)

    # Firebase 初期化（2回目以降はスキップ）
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)

    return firestore.client()

db = init_firebase()

# -------------------- DB 初期化 --------------------
def init_db():
    print("Firestore ready. No DB init required.")

# -------------------- 写真番号カウンタ --------------------
def get_next_photo_number():
    counter_ref = db.collection("metadata").document("photo_counter")

    @firestore.transactional
    def transaction_op(transaction):
        snapshot = counter_ref.get(transaction=transaction)
        current = snapshot.to_dict()["count"] if snapshot.exists else 0
        next_number = current + 1
        transaction.set(counter_ref, {"count": next_number})
        return next_number

    transaction = db.transaction()
    return transaction_op(transaction)

# -------------------- 画像保存 --------------------
def save_image_from_line(message_id: str, user_id: str):
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        raise ValueError(f"LINE 画像取得失敗: {r.status_code}")

    # Cloudinary にアップロード
    result = cloudinary.uploader.upload(
        r.content,
        folder="linebot_photos",
        public_id=message_id
    )
    image_url = result["secure_url"]

    # 連番発行
    photo_number = get_next_photo_number()

    # Firestore に保存
    doc_ref = db.collection("photos").document()
    doc_ref.set({
        "user_id": user_id,
        "image_url": image_url,
        "likes": 0,
        "photo_number": photo_number,
        "created_at": datetime.utcnow()
    })

    return image_url, doc_ref.id, photo_number

# -------------------- 過去 N 日の写真取得 --------------------
def get_recent_photos(days=28):
    one_week_ago = datetime.utcnow() - timedelta(days=days)
    docs = db.collection("photos").where("created_at", ">=", one_week_ago).stream()
    return [doc.to_dict() | {"id": doc.id} for doc in docs]

# -------------------- いいね機能 --------------------
def like_photo(doc_id: str, user_id: str, session_id: str):
    session_ref = db.collection("likes_sessions").document(session_id)
    if session_ref.get().exists:
        return "already_liked"

    doc_ref = db.collection("photos").document(doc_id)
    doc = doc_ref.get()
    if not doc.exists:
        return False

    current_likes = doc.to_dict().get("likes", 0)
    new_likes = current_likes + 1
    doc_ref.update({"likes": new_likes})

    session_ref.set({
        "user_id": user_id,
        "photo_id": doc_id,
        "timestamp": firestore.SERVER_TIMESTAMP
    })

    return new_likes

# -------------------- ユーザーごとの累計いいね数 --------------------
def get_user_like_counts():
    """
    ユーザーごとに総いいね数を集計して辞書で返す
    返り値: { user_id: total_likes }
    """
    like_counts = {}

    # 全写真を取得して投稿者ごとに likes を合計
    photos = db.collection("photos").stream()
    for photo in photos:
        data = photo.to_dict()
        user_id = data.get("user_id")
        likes = data.get("likes", 0)

        if user_id:
            like_counts[user_id] = like_counts.get(user_id, 0) + likes

    return like_counts

# -------------------- 写真削除 --------------------
def delete_photo(doc_id: str):
    doc_ref = db.collection("photos").document(doc_id)
    doc = doc_ref.get()
    if doc.exists:
        url = doc.to_dict()["image_url"]
        public_id = url.split("/")[-1].split(".")[0]
        cloudinary.uploader.destroy(f"linebot_photos/{public_id}")

        # likes_sessions 削除
        sessions_ref = db.collection("likes_sessions")
        query = sessions_ref.where("photo_id", "==", doc_id).stream()
        for session_doc in query:
            session_doc.reference.delete()

        # 写真ドキュメント削除
        doc_ref.delete()

def delete_photo_by_number(photo_number: int):
    query = db.collection("photos").where("photo_number", "==", photo_number).stream()
    for doc in query:
        delete_photo(doc.id)

# -------------------- ユーザー管理 --------------------
def save_user(user_id):
    doc_ref = db.collection("users").document(user_id)
    if not doc_ref.get().exists:
        doc_ref.set({"joined_at": firestore.SERVER_TIMESTAMP})
        print(f"[DB] 新しいユーザー登録: {user_id}")
    else:
        print(f"[DB] 既に登録済み: {user_id}")

def get_all_users():
    users_ref = db.collection("users").stream()
    return [doc.id for doc in users_ref]

def get_photo_doc_id_by_public_id(public_id: str):
    docs = db.collection("photos").stream()
    for doc in docs:
        data = doc.to_dict()
        url = data.get("image_url", "")
        if url.endswith(public_id) or public_id in url:
            return doc.id
    return None
# -------------------- Firebaseの全画像取得 --------------------
def get_all_photo_docs():
    docs = []
    for doc in db.collection("photos").stream():
        data = doc.to_dict()
        data["id"] = doc.id
        docs.append(data)
    return docs
