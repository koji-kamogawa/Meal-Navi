import streamlit as st
import os
import json
import csv
import io
import time
from datetime import datetime
from openai import OpenAI

# ページ設定
st.set_page_config(page_title="1か月夕食メニュー＆レシピ生成", layout="wide")

# カスタムCSSでダークモード対応とモダンなデザイン
st.markdown("""
<style>
    .main {
        background-color: var(--background-color);
        color: var(--text-color);
    }
    .stButton button {
        background-color: #4CAF50;
        color: white;
        border-radius: 8px;
        padding: 0.5rem 1rem;
        font-weight: bold;
    }
    .stDownloadButton button {
        background-color: #008CBA;
        color: white;
        border-radius: 8px;
        padding: 0.5rem 1rem;
        font-weight: bold;
    }
    .stTextInput input, .stNumberInput input, .stSelectbox select, .stMultiSelect div {
        border-radius: 8px;
    }
    h1, h2, h3 {
        color: var(--text-color);
    }
    .reportview-container .main .block-container {
        padding-top: 2rem;
    }
    .input-card {
        background-color: rgba(128, 128, 128, 0.08);
        border-radius: 12px;
        padding: 1rem;
        margin-bottom: 1rem;
        border: 1px solid rgba(128, 128, 128, 0.2);
    }
</style>
""", unsafe_allow_html=True)

st.title("🍽️ 1か月夕食メニュー＆レシピ生成アプリ")
st.markdown("共働き家庭向けに、1か月分の夕食メニュー（主菜・副菜）とレシピをCSVで生成します。")

# デフォルトのユーザ情報
DEFAULT_USER_INFO = {
    "family_structure": "",
    "family_size": 4,
    "children_ages": "",
    "cooking_skill_jp": 3,
    "cooking_skill_west": 3,
    "cooking_skill_cn": 3,
    "preferred_ingredients": "",
    "allergies": "",
    "no_allergies": False,
    "favorite_dishes": "",
    "use_seasonal": True,
    "season": "指定なし",
    "nutrition_balance": True,
    "budget_per_person": 800
}

# セッション状態の初期化（ウィジェットのキーとして直接使用）
for k, v in DEFAULT_USER_INFO.items():
    if k not in st.session_state:
        st.session_state[k] = v

if "generated_csv" not in st.session_state:
    st.session_state.generated_csv = None
if "show_result" not in st.session_state:
    st.session_state.show_result = False

# CSV読み込み用の一時バッファ（ウィジェット生成前に反映するため）
if "_pending_user_info" not in st.session_state:
    st.session_state._pending_user_info = None
if "_csv_load_message" not in st.session_state:
    st.session_state._csv_load_message = None
# 処理済みアップロードファイルの識別子を保持（無限rerun防止）
if "_processed_upload_id" not in st.session_state:
    st.session_state._processed_upload_id = None

# ウィジェット生成前に、保留中のCSV読み込みデータを反映する
if st.session_state._pending_user_info is not None:
    pending = st.session_state._pending_user_info
    for key, value in pending.items():
        if key in DEFAULT_USER_INFO:
            st.session_state[key] = value
    st.session_state._pending_user_info = None


def decode_csv_bytes(raw_bytes):
    """Windows環境で保存されたCSV（UTF-8 BOM付き/Shift-JIS等）を堅牢にデコードする。"""
    encodings = ["utf-8-sig", "utf-8", "cp932", "shift_jis", "utf-16"]
    last_error = None
    for enc in encodings:
        try:
            text = raw_bytes.decode(enc)
            # BOMが残っている場合は除去
            if text.startswith("\ufeff"):
                text = text.lstrip("\ufeff")
            return text
        except (UnicodeDecodeError, UnicodeError) as e:
            last_error = e
            continue
    raise ValueError(f"CSVの文字コードを判別できませんでした: {last_error}")


def normalize_key(key):
    """BOMや空白・改行を除去してキーを正規化する。"""
    if key is None:
        return ""
    return key.replace("\ufeff", "").strip()


def parse_bool(value):
    """真偽値の文字列表現を堅牢にパースする。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("true", "1", "yes", "y", "on", "はい")


# サイドバーでユーザ情報入力
with st.sidebar:
    st.header("👨‍👩‍👧‍👦 家族情報入力")

    st.subheader("① 家族構成")
    st.text_area(
        "家族構成（続柄をカンマ区切りで入力）",
        key="family_structure",
        placeholder="例：父、母、長男、長女",
        height=80
    )
    st.number_input(
        "家族の人数",
        min_value=1,
        max_value=20,
        step=1,
        key="family_size"
    )

    st.subheader("② 子供の年齢")
    st.text_area(
        "子供の年齢（カンマ区切り、いなければ空欄）",
        key="children_ages",
        placeholder="例：5歳、8歳、12歳",
        height=80
    )

    st.subheader("③ 料理者の熟練度（1-5）")
    st.slider("和食スキル", 1, 5, key="cooking_skill_jp")
    st.slider("洋食スキル", 1, 5, key="cooking_skill_west")
    st.slider("中華スキル", 1, 5, key="cooking_skill_cn")

    st.subheader("④ 家族の好み・アレルギー")
    st.text_area(
        "家族の好みの食材（カンマ区切り）",
        key="preferred_ingredients",
        placeholder="例：鶏肉、鮭、ブロッコリー、豆腐",
        height=80
    )
    st.checkbox("アレルギーなし", key="no_allergies")
    if st.session_state.no_allergies:
        st.session_state.allergies = ""
        st.caption("アレルギーなしとして扱います。")
    else:
        st.text_area(
            "アレルギー（カンマ区切り）",
            key="allergies",
            placeholder="例：卵、乳、小麦、そば、落花生",
            height=80
        )

    st.subheader("⑤ 家族が好きな料理")
    st.text_area(
        "家族が好きな料理（カンマ区切り）",
        key="favorite_dishes",
        placeholder="例：カレー、ハンバーグ、唐揚げ、麻婆豆腐",
        height=80
    )

    st.subheader("⑥ 旬・季節の野菜")
    st.checkbox("旬の野菜を利用する", key="use_seasonal")
    season_options = ["指定なし", "春", "夏", "秋", "冬"]
    if st.session_state.season not in season_options:
        st.session_state.season = "指定なし"
    st.selectbox(
        "季節を指定（任意）",
        options=season_options,
        key="season"
    )

    st.subheader("⑦ 栄養バランス")
    st.checkbox("栄養バランスを考慮する", key="nutrition_balance")

    st.subheader("⑧ 予算")
    st.number_input(
        "1食/人あたりの平均予算（円）",
        min_value=300,
        max_value=5000,
        step=100,
        key="budget_per_person"
    )

# ユーザ情報のCSVダウンロード
user_info = {k: st.session_state[k] for k in DEFAULT_USER_INFO.keys()}
csv_buffer = io.StringIO()
writer = csv.DictWriter(csv_buffer, fieldnames=list(user_info.keys()))
writer.writeheader()
writer.writerow(user_info)
csv_str = csv_buffer.getvalue()

st.sidebar.download_button(
    label="📥 ユーザ情報をCSVでダウンロード",
    data=csv_str,
    file_name="user_info.csv",
    mime="text/csv"
)

# ユーザ情報のCSVアップロード
uploaded_file = st.sidebar.file_uploader("📤 ユーザ情報CSVをアップロード", type=["csv"])
if uploaded_file is not None:
    # アップロードファイルの一意な識別子を生成（name + size）
    try:
        upload_id = f"{uploaded_file.name}::{uploaded_file.size}"
    except Exception:
        upload_id = uploaded_file.name

    # 既に処理済みのファイルであればスキップ（無限rerun防止）
    if st.session_state._processed_upload_id != upload_id:
        try:
            raw_bytes = uploaded_file.getvalue()
            content = decode_csv_bytes(raw_bytes)
            reader = csv.DictReader(io.StringIO(content))
            loaded_data = {}
            for row in reader:
                # キーを正規化（BOM・空白除去）
                normalized_row = {normalize_key(k): v for k, v in row.items() if k is not None}
                for key in DEFAULT_USER_INFO.keys():
                    if key in normalized_row:
                        value = normalized_row[key]
                        if value is None:
                            continue
                        value_str = str(value).strip()
                        if value_str == "":
                            continue
                        if key in ["cooking_skill_jp", "cooking_skill_west", "cooking_skill_cn", "budget_per_person", "family_size"]:
                            try:
                                loaded_data[key] = int(float(value_str))
                            except (ValueError, TypeError):
                                pass
                        elif key in ["use_seasonal", "nutrition_balance", "no_allergies"]:
                            loaded_data[key] = parse_bool(value_str)
                        else:
                            loaded_data[key] = value_str
            if loaded_data:
                # ウィジェット生成後に直接session_stateを書き換えるとエラーになるため、
                # 保留バッファに保存してrerunし、次回のウィジェット生成前に反映する
                st.session_state._pending_user_info = loaded_data
                st.session_state._csv_load_message = ("success", "ユーザ情報を読み込みました。")
                # 処理済みとしてマークしてからrerun（無限ループ防止）
                st.session_state._processed_upload_id = upload_id
                st.rerun()
            else:
                st.session_state._csv_load_message = ("warning", "CSVに有効なデータが見つかりませんでした。列名をご確認ください。")
                st.session_state._processed_upload_id = upload_id
        except Exception as e:
            st.session_state._csv_load_message = ("error", f"CSVの読み込みに失敗しました: {e}")
            st.session_state._processed_upload_id = upload_id

# 読み込み結果メッセージの表示
if st.session_state._csv_load_message is not None:
    level, msg = st.session_state._csv_load_message
    if level == "success":
        st.sidebar.success(msg)
    elif level == "warning":
        st.sidebar.warning(msg)
    else:
        st.sidebar.error(msg)
    st.session_state._csv_load_message = None

# メインエリア
st.header("📋 入力内容の確認")

# 入力内容をカード形式で見やすく表示
info = {k: st.session_state[k] for k in DEFAULT_USER_INFO.keys()}
col1, col2 = st.columns(2)
with col1:
    st.markdown("#### 👨‍👩‍👧‍👦 家族情報")
    st.markdown(f"- **家族構成**: {info.get('family_structure') or '未入力'}")
    st.markdown(f"- **家族の人数**: {info.get('family_size', 0)}人")
    st.markdown(f"- **子供の年齢**: {info.get('children_ages') or '未入力'}")
    st.markdown("#### 🍳 料理者の熟練度")
    jp = int(info.get('cooking_skill_jp', 0))
    west = int(info.get('cooking_skill_west', 0))
    cn = int(info.get('cooking_skill_cn', 0))
    st.markdown(f"- **和食**: {'★' * jp}{'☆' * (5 - jp)}")
    st.markdown(f"- **洋食**: {'★' * west}{'☆' * (5 - west)}")
    st.markdown(f"- **中華**: {'★' * cn}{'☆' * (5 - cn)}")
with col2:
    st.markdown("#### 🥗 好み・アレルギー")
    st.markdown(f"- **好みの食材**: {info.get('preferred_ingredients') or '未入力'}")
    if info.get('no_allergies'):
        st.markdown("- **アレルギー**: なし")
    else:
        st.markdown(f"- **アレルギー**: {info.get('allergies') or '未入力'}")
    st.markdown(f"- **好きな料理**: {info.get('favorite_dishes') or '未入力'}")
    st.markdown("#### 🌿 その他条件")
    st.markdown(f"- **旬の野菜を利用**: {'はい' if info.get('use_seasonal') else 'いいえ'}")
    st.markdown(f"- **季節指定**: {info.get('season', '指定なし')}")
    st.markdown(f"- **栄養バランス考慮**: {'はい' if info.get('nutrition_balance') else 'いいえ'}")
    st.markdown(f"- **1食/人あたり予算**: {info.get('budget_per_person', 0)}円")

with st.expander("🔍 生データ（JSON）を表示"):
    st.json(info)

if st.button("🍳 1か月分の夕食メニューを生成", type="primary"):
    with st.spinner("DeepSeek APIでメニューを生成中..."):
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            st.error("環境変数 DEEPSEEK_API_KEY が設定されていません。")
        else:
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

            # プロンプト構築
            info = {k: st.session_state[k] for k in DEFAULT_USER_INFO.keys()}
            allergy_text = "なし" if info.get('no_allergies') else (info.get('allergies') or "なし")
            season_text = info.get('season') if info.get('season') != "指定なし" else "指定なし（現在の季節に合わせて）"
            prompt = f"""
            あなたはプロの栄養士兼料理研究家です。以下の家族情報に基づいて、1か月分（30日間）の夕食メニュー（主菜と副菜）と簡単なレシピを提案してください。

            家族構成: {info.get('family_structure', '')}
            家族の人数: {info.get('family_size', 0)}人
            子供の年齢: {info.get('children_ages', '')}
            料理者の熟練度（和食/洋食/中華）: {info.get('cooking_skill_jp', 0)}/{info.get('cooking_skill_west', 0)}/{info.get('cooking_skill_cn', 0)} (1-5)
            好みの食材: {info.get('preferred_ingredients', '')}
            アレルギー: {allergy_text}
            好きな料理: {info.get('favorite_dishes', '')}
            旬の野菜を利用: {'はい' if info.get('use_seasonal') else 'いいえ'}
            季節指定: {season_text}
            栄養バランスを考慮: {'はい' if info.get('nutrition_balance') else 'いいえ'}
            1食/人あたりの平均予算: {info.get('budget_per_person', 0)}円

            【メニュー構成のバリエーション方針（重要）】
            家族の好みを尊重しつつ、食の幅を広げるため、以下のルールを必ず守ってください。
            1. 好みの食材・好きな料理は、1か月全体の主菜・副菜のうち6〜7割程度に留めてください。残りの3〜4割は、好みに挙げられていない食材（例：好みに「鶏肉・鮭」しかない場合は、豚肉・牛肉・白身魚・青魚・大豆製品・卵・きのこ類・海藻類・旬の野菜など）を意図的に取り入れてください。
            2. 週ごとにテーマをローテーションしてください（例：1週目=和食中心、2週目=洋食中心、3週目=中華・アジアン中心、4週目=ミックス・時短料理中心）。ただし料理者の熟練度が低いジャンルは頻度を下げて構いません。
            3. 同じ主菜・副菜の組み合わせを月内で重複させないでください。似た系統の料理（例：唐揚げと竜田揚げ）も連日にならないよう分散してください。
            4. 子供が苦手そうな食材（ピーマン、セロリ、レバー、納豆など）も、月に1〜2回は調理法を工夫して（細かく刻む、甘辛く味付けする、揚げる等）登場させ、レシピに工夫点を明記してください。
            5. 旬の野菜を利用する場合は、週に2回以上、指定季節の野菜を主菜または副菜に取り入れてください。
            6. 栄養バランスを考慮する場合は、1週間の中で肉・魚・大豆製品・緑黄色野菜・海藻・きのこがバランスよく登場するようにしてください。
            7. 予算内に収まるよう、高価な食材（牛肉・魚介類など）は週1〜2回程度に抑え、鶏肉・豚肉・大豆製品・旬の野菜でコスト調整してください。

            出力はCSV形式で、以下の列を含めてください：
            日付,主菜名,主菜レシピ,副菜名,副菜レシピ,推定費用(円/人),栄養バランスコメント

            日付は1日目から30日目までとしてください。
            アレルギーがある場合は必ず除外してください。
            予算を超えないようにしてください。
            旬の野菜を利用する場合は季節に合った野菜を使ってください。
            レシピは簡潔に、手順を3〜5ステップで記載してください。
            出力はCSVのみとし、余計な説明は不要です。
            """

            try:
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": "あなたはプロの栄養士兼料理研究家です。家族の好みを尊重しつつ、好みに偏らないバリエーション豊かな献立を提案し、指示に従いCSV形式で出力してください。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=8000
                )
                result_text = response.choices[0].message.content.strip()

                # CSV部分を抽出（```csv ... ``` で囲まれている場合に対応）
                if "```csv" in result_text:
                    result_text = result_text.split("```csv")[1].split("```")[0].strip()
                elif "```" in result_text:
                    result_text = result_text.split("```")[1].split("```")[0].strip()

                st.session_state.generated_csv = result_text
                st.session_state.show_result = True
                st.success("メニューを生成しました！")
            except Exception as e:
                st.error(f"生成中にエラーが発生しました: {e}")

# 結果表示
if st.session_state.show_result and st.session_state.generated_csv:
    st.header("📅 生成された1か月分の夕食メニュー")

    # CSVをパースして表示
    try:
        reader = csv.DictReader(io.StringIO(st.session_state.generated_csv))
        rows = list(reader)
        if rows:
            st.dataframe(rows, width="stretch")
        else:
            st.warning("生成されたCSVにデータがありません。")
    except Exception as e:
        st.warning(f"CSVの解析に失敗しました。生データを表示します。\n{e}")
        st.text(st.session_state.generated_csv)

    # ダウンロードボタン
    st.download_button(
        label="📥 メニューCSVをダウンロード",
        data=st.session_state.generated_csv,
        file_name="monthly_dinner_menu.csv",
        mime="text/csv"
    )
