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
    try:
        content = uploaded_file.getvalue().decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            for key in DEFAULT_USER_INFO.keys():
                if key in row and row[key] is not None and row[key] != "":
                    if key in ["cooking_skill_jp", "cooking_skill_west", "cooking_skill_cn", "budget_per_person", "family_size"]:
                        try:
                            st.session_state[key] = int(float(row[key]))
                        except (ValueError, TypeError):
                            pass
                    elif key in ["use_seasonal", "nutrition_balance", "no_allergies"]:
                        st.session_state[key] = str(row[key]).lower() == "true"
                    else:
                        st.session_state[key] = row[key]
        st.sidebar.success("ユーザ情報を読み込みました。")
        st.rerun()
    except Exception as e:
        st.sidebar.error(f"CSVの読み込みに失敗しました: {e}")

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
                        {"role": "system", "content": "あなたはプロの栄養士兼料理研究家です。指示に従い、CSV形式で出力してください。"},
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
