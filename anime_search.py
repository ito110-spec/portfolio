import google.generativeai as genai
import os
import time
import traceback
import sys
import re
from fugashi import Tagger

# Gemini APIキー（環境変数から取得）
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY2")
genai.configure(api_key=GEMINI_API_KEY)

# Tagger 初期化（unidic-lite を利用）
try:
    tagger = Tagger()
    print("[DEBUG] fugashi Tagger初期化成功", file=sys.stderr)
except Exception as e:
    print("[ERROR] fugashi Tagger初期化失敗:", e, file=sys.stderr)
    traceback.print_exc()
    tagger = None


def query_gemini_flash(prompt, attempts=2):
    # モデル指定
    GEMINI_MODEL = "gemini-3.5-flash"

    if not GEMINI_API_KEY:
        print("[DEBUG] GEMINI_API_KEY が見つかりません。環境変数を確認してください。")
        return None

    for attempt in range(1, attempts + 1):
        try:
            model = genai.GenerativeModel(GEMINI_MODEL)
            response = model.generate_content(prompt)
            text = getattr(response, "text", None) or str(response)

            if text:
                print(f"[DEBUG] Gemini 応答内容(attempt {attempt}): {text[:1000]}...")
                return text.strip()
            else:
                print(f"[DEBUG] Gemini 応答が空でした。attempt={attempt}")

        except Exception as e:
            print(f"[ERROR] Gemini API エラー (attempt {attempt}): {e}")
            traceback.print_exc()

        if attempt < attempts:
            wait = (2 ** (attempt - 1)) * 5
            print(f"[DEBUG] 再試行まで待機: {wait}s")
            time.sleep(wait)

    print("[DEBUG] Gemini への問い合わせが全て失敗しました。")
    return None


def query_gemini_2(prompt, attempts=2):
    # モデル指定
    GEMINI_MODEL = "gemini-2.5-pro"

    if not GEMINI_API_KEY:
        print("[DEBUG] GEMINI_API_KEY が見つかりません。環境変数を確認してください。")
        return None

    for attempt in range(1, attempts + 1):
        try:
            model = genai.GenerativeModel(GEMINI_MODEL)
            response = model.generate_content(prompt)
            text = getattr(response, "text", None) or str(response)

            if text:
                print(f"[DEBUG] Gemini 応答内容(attempt {attempt}): {text[:1000]}...")
                return text.strip()
            else:
                print(f"[DEBUG] Gemini 応答が空でした。attempt={attempt}")

        except Exception as e:
            print(f"[ERROR] Gemini API エラー (attempt {attempt}): {e}")
            traceback.print_exc()

        if attempt < attempts:
            wait = (2 ** (attempt - 1)) * 5
            print(f"[DEBUG] 再試行まで待機: {wait}s")
            time.sleep(wait)

    print("[DEBUG] Gemini への問い合わせが全て失敗しました。")
    return None


def extract_keywords(text):
    if not text or tagger is None:
        return []

    keywords = []
    for word in tagger(text):
        features = word.feature._asdict()
        pos = features.get("pos1", "")  # POS1 → pos1 に修正
        if "名詞" in pos or "形容詞" in pos:
            keywords.append(word.surface)
        else:
            print(f"[DEBUG] 無視する単語: {word.surface}, pos1={pos}")

    return sorted(set(keywords))


def extract_keyword_pairs(text):
    if not text or tagger is None:
        return []

    words = list(tagger(text))
    pairs = []

    for i in range(len(words) - 1):
        features1 = words[i].feature._asdict()
        features2 = words[i + 1].feature._asdict()
        pos1 = features1.get("pos1", "")
        pos2 = features2.get("pos1", "")

        # 名詞+名詞 または 形容詞+名詞 のペアだけ抽出
        if (pos1 == "名詞" and pos2 == "名詞") or (pos1 == "形容詞" and pos2 == "名詞"):
            pairs.append(words[i].surface + words[i + 1].surface)

    # 重複除去
    return sorted(set(pairs))


def extract_keywords_debug(text):
    """
    デバッグ用キーワード抽出
    - 各単語の表層形と品詞を表示
    - 名詞・形容詞・動詞を抽出
    """
    if not text:
        print("[WARN] 入力テキストが空です")
        return []

    if tagger is None:
        print("[ERROR] Taggerが初期化されていません")
        return []

    keywords = []
    print("[DEBUG] --- 単語と品詞の一覧 ---")
    for word in tagger(text):
        try:
            features = word.feature._asdict()
            pos = features.get("POS1", "")
            print(f"{word.surface}\tPOS1={pos}\tALL={features}")
            if pos.startswith(("名詞", "形容詞", "動詞")):
                keywords.append(word.surface)
        except Exception as e:
            print(f"[ERROR] word={word.surface} 解析失敗: {e}")

    keywords = sorted(set(keywords))
    print("[DEBUG] 抽出キーワード:", keywords)
    return keywords


def handle_anime_search(user_id, user_msg, anime_search_states):
    print(f"[DEBUG] user_id={user_id}, user_msg={user_msg}")

    user_msg = user_msg.strip().lower()
    state = anime_search_states.get(user_id)
    if state is None:
        anime_search_states[user_id] = {"titles": []}
        state = anime_search_states[user_id]

    if user_msg == "検索":
        titles = state.get("titles", [])
        if not titles:
            return "まだアニメタイトルが入力されていません。好きなアニメを教えてください。"

        prompt = (
            f"以下のアニメタイトルについて、それぞれのストーリーの特徴を4つのカテゴリで5つずつ挙げてください。\n"
            f"カテゴリ: テーマ・メッセージ要素, ストーリー・プロット展開要素, 登場キャラ内面・心理要素, 世界観・雰囲気・設定要素\n"
            f"タイトル一覧: {', '.join(titles)}\n"
            "回答はカテゴリごとに箇条書きで教えて。"
            "また箇条書きで書く際、作品内のキャラクター名、専門用語を使わないでほしい"
        )

        result = query_gemini_flash(prompt)

        matches = re.findall(r'^\* ([^\*].*)', result, re.MULTILINE)

        prompt = (
            f"以下の要素と親和性のある実際に存在するマイナーアニメタイトルを20個あげてください。\n"
            f"タイトル一覧: {matches}\n"
            f"返事は項番とタイトルと簡単なあらすじの一覧だけでOK。余計な文言はいらない。\n"
            f"なお上げる際に以下のタイトルは除外すること\n"
            f"タイトル一覧: {', '.join(titles)}\n"
        )

        result = query_gemini_flash(prompt)

        if not result:
            return "おすすめを取得中にエラーが発生しました。もう一度やり直してください。"

        keywords = extract_keyword_pairs(result)

        # 検索完了後に状態リセット
        if user_id in anime_search_states:
            del anime_search_states[user_id]

        return f"おすすめ生成結果:\n{result}\n"

    else:
        titles = state.get("titles", [])
        titles.append(user_msg)
        state["titles"] = titles
        return f"タイトル「{user_msg}」を登録しました。ほかのタイトルか「検索」と入力してください。"
