# GoogleトレンドAPI用のライブラリ
from pytrends.request import TrendReq
# 正規表現を使うため
import re
# 辞書型で初期値0のカウンターを作るため
from collections import defaultdict
# 処理を一時停止させるため
import time
# ランダムな待機時間を作るため
import random

# ユーザーID・検索キーワードを受け取り、関連キーワード（メイン＋サブ）を返す関数
def extract_main_and_sub_related(user_id: str, user_input: str, max_results=10):
    try:
        # 入力キーワードの前後の空白を削除
        query = user_input.strip()

        # Google側の制限回避のため、6〜10秒のランダム待機
        time.sleep(random.uniform(6, 10))  

        # Googleトレンドへアクセスする準備
        pytrends = TrendReq(hl='ja-JP', tz=540)  # 日本語・日本時間で設定

        # 検索キーワードのデータをセット（過去1日の日本国内トレンド）
        pytrends.build_payload([query], geo='JP', timeframe='now 1-d')

        # 関連キーワード取得（失敗したら最大3回リトライ）
        for attempt in range(3):
            try:
                related = pytrends.related_queries()
                break
            except Exception as e:
                # 1回目→15秒待機、2回目→25秒待機
                if attempt < 2:
                    wait = 15 + attempt * 10
                    print(f"429 or other error, retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    # 3回失敗したらエラーをそのまま返す
                    raise e

        # 「急上昇」関連キーワードのデータを取得
        df = related.get(query, {}).get('rising')
        if df is None or df.empty:
            return "関連キーワードが見つかりませんでした。"

        # 単語ごとのスコアを保存する辞書
        word_scores = defaultdict(int)
        # 元データの行を保存（後でサブ関連語抽出に使う）
        original_rows = []
        # 既に使った単語を記録（最初から検索ワードは使用済みに）
        used_words = set([query])

        # -------------------------------
        # メイン関連語候補をスコア集計
        # -------------------------------
        for row in df.itertuples():
            full_query = row.query  # 関連ワード全体
            score = int(row.value)  # 人気度スコア
            original_rows.append((full_query, score))

            # 元のキーワードを削除して残った部分を単語ごとに分割
            cleaned_full_query = full_query.replace(query, '').strip()
            words = [w for w in re.split(r'\s+', cleaned_full_query) if len(w) > 1]

            # まだ使っていない単語ならスコアを加算
            for w in words:
                if w not in used_words:
                    word_scores[w] += score

        # スコア順に並べ替え（高い順）
        sorted_main = sorted(word_scores.items(), key=lambda x: x[1], reverse=True)
        results = []

        # -------------------------------
        # メイン関連語と、そのサブ関連語を抽出
        # -------------------------------
        for main_word, main_score in sorted_main:
            # 既に使った単語はスキップ
            if main_word in used_words:
                continue  

            sub_words = []  # サブ関連語
            sub_candidates = []  # 候補用（未使用だが今回は使ってない）

            # 人気度スコアに応じたアイコンを付与
            if main_score >= 1000:
                score_icon = "🔴"  # 超人気
            elif main_score >= 100:
                score_icon = "🟠"  # 人気
            elif main_score >= 10:
                score_icon = "🟡"  # 少し人気
            else:
                score_icon = ""    # 無印

            # 元データからサブ関連語を探す
            for full_query, score in original_rows:
                # メイン語と検索語が両方含まれている行だけを見る
                if main_word in full_query and query in full_query:
                    # メイン語と検索語を削除
                    cleaned = re.sub(query, '', full_query)
                    cleaned = re.sub(main_word, '', cleaned)

                    # 残った単語を候補に
                    candidates = [w.strip() for w in cleaned.split() if w.strip() and w != query and w != main_word]

                    # 未使用・長さ2文字以上・まだ追加してない単語だけをサブ語に追加
                    for w in candidates:
                        if w not in used_words and len(w) > 1 and w not in sub_words:
                            sub_words.append(w)
                            if len(sub_words) >= 3:  # サブ語は最大3つ
                                break

            # メイン語とサブ語を使用済みに登録
            used_words.add(main_word)
            used_words.update(sub_words)

            # サブ関連語がなければ「なし」
            sub_str = "、".join(sub_words) if sub_words else "なし"
            results.append(f"{score_icon}{main_word}(+{main_score}%)\n┗ｻﾌﾞ関連:{sub_str}")

            # 上限数に達したら終了
            if len(results) >= max_results:
                break

            # 次の処理前に0.5〜1.2秒ランダム待機（Google側負荷軽減）
            time.sleep(random.uniform(0.5, 1.2))

        # 結果をまとめて返す
        return "\n".join(results)

    except Exception as e:
        import traceback
        # 例外内容を文字列で返す（デバッグ用）
        return f"エラーが発生しました：\n{traceback.format_exc()}"
