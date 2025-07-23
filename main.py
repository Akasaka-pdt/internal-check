
import streamlit as st
import pandas as pd
import plotly.express as px
import io
from datetime import datetime

month_order = ['4月号', '5月号', '6月号', '7月号', '8月号', '9月号', '10月号', '11月号', '12月号', '1月号', '2月号', '3月号', 'その他']

# 工程の順序（重複除去済）を定義
original_process_order = ['仮台割', '入稿前ラフ', '入稿原稿', '組版原稿', '初校', '再校', '再校2', '再校3',
                        '色校', '色校2', '色校3', '念校', '念校2', '念校3', 'α1版', 'β1版', 'β2版', 'β3版', 'β4版', 'β5版', 'その他']
# 順序を保ちつつ重複削除
original_process_order = list(dict.fromkeys(original_process_order))


# --- Streamlit ページ設定 ---
st.set_page_config(
    page_title="社内チェック業務 BPR分析ツール",
    layout="wide"
)

st.title("📊 社内チェック業務 BPR分析ツール")

# --- ファイルアップローダー --- 
st.sidebar.header("1. ファイルアップロード")
st.sidebar.info("分析対象のCSVファイルを2つアップロードしてください。")

uploaded_seisakubutsu_file = st.sidebar.file_uploader("制作物一覧 CSV", type="csv")
uploaded_header_file = st.sidebar.file_uploader("ヘッダー一覧 CSV", type="csv")

# --- データ読み込みとキャッシュ ---
@st.cache_data
def load_data(seisakubutsu_file, header_file):
    """アップロードされたCSVファイルを読み込み、マージして前処理を行う"""
    try:
        seisakubutsu_df = pd.read_csv(seisakubutsu_file)
        header_df = pd.read_csv(header_file)
    except Exception as e:
        st.error(f"エラー: ファイルの読み込み中に問題が発生しました。詳細: {e}")
        return None, None

    # --- データ前処理 ---
    date_cols = ['作成日', '修正日', '締め切り日']
    for col in date_cols:
        if col in seisakubutsu_df.columns:
            seisakubutsu_df[col] = pd.to_datetime(seisakubutsu_df[col], errors='coerce').dt.tz_localize(None)
        if col in header_df.columns:
            header_df[col] = pd.to_datetime(header_df[col], errors='coerce').dt.tz_localize(None)

    header_df.rename(columns={'制作物トークン': 'トークン'}, inplace=True)
    
    # トークンごとにチェック者数を集計
    checkers_count_df = header_df.groupby('トークン')['担当者メールアドレス'].nunique().reset_index()
    checkers_count_df.rename(columns={'担当者メールアドレス': 'チェック者数'}, inplace=True)

    # 制作物データとチェック者数データをマージ
    seisakubutsu_df = pd.merge(seisakubutsu_df, checkers_count_df, on='トークン', how='left')
    seisakubutsu_df['チェック者数'].fillna(0, inplace=True) # チェック者がいない場合は0をセット

    merged_df = pd.merge(header_df, seisakubutsu_df, on='トークン', suffixes=('_header', '_seisakubutsu'))
    
    # 発刊月の順序を定義
    # 発刊月をカテゴリ型に変換し、順序を適用
    merged_df['発刊月'] = pd.Categorical(merged_df['発刊月'], categories=month_order, ordered=True)
    seisakubutsu_df['発刊月'] = pd.Categorical(seisakubutsu_df['発刊月'], categories=month_order, ordered=True)

    # dfに実際に存在する工程だけを残す
    existing_processes = pd.concat([merged_df['工程'], seisakubutsu_df['工程']]).dropna().unique()
    filtered_process_order = [p for p in original_process_order if p in existing_processes]

    # Categorical に適用
    merged_df['工程'] = pd.Categorical(merged_df['工程'], categories=filtered_process_order, ordered=True)
    seisakubutsu_df['工程'] = pd.Categorical(seisakubutsu_df['工程'], categories=filtered_process_order, ordered=True)

    return merged_df, seisakubutsu_df

# --- メイン処理 --- 
if uploaded_seisakubutsu_file is not None and uploaded_header_file is not None:
    df_merged_all, df_seisakubutsu_all = load_data(uploaded_seisakubutsu_file, uploaded_header_file)

    if df_merged_all is None:
        st.stop()

    st.sidebar.header("2. 絞り込みフィルター")
    # --- 期間指定フィルター ---
    st.sidebar.subheader("期間フィルター")
    min_date = df_seisakubutsu_all['作成日'].min().date()
    max_date = df_seisakubutsu_all['作成日'].max().date()
    start_date = st.sidebar.date_input('開始日', min_date, min_value=min_date, max_value=max_date)
    end_date = st.sidebar.date_input('終了日', max_date, min_value=start_date, max_value=max_date)

    if start_date > end_date:
        st.sidebar.error('エラー: 終了日は開始日以降に設定してください。')
        st.stop()

    start_datetime = pd.to_datetime(start_date)
    end_datetime = pd.to_datetime(end_date) + pd.Timedelta(days=1)

    # --- フィルター適用 --- 
    df_filtered_by_date = df_merged_all[(df_merged_all['作成日_seisakubutsu'] >= start_datetime) & (df_merged_all['作成日_seisakubutsu'] < end_datetime)].copy()
    df_seisakubutsu_filtered_by_date = df_seisakubutsu_all[(df_seisakubutsu_all['作成日'] >= start_datetime) & (df_seisakubutsu_all['作成日'] < end_datetime)].copy()

    st.sidebar.subheader("発刊年度フィルター")
    available_years = sorted(df_seisakubutsu_filtered_by_date['年度'].dropna().unique().tolist())
    selected_year = st.sidebar.selectbox('比較したい発刊年度を選択', options=['すべて'] + available_years)

    # --- 発刊月フィルター ---
    st.sidebar.subheader("発刊月フィルター")
    available_months = [m for m in month_order if m in df_seisakubutsu_filtered_by_date['発刊月'].dropna().unique()]
    selected_month = st.sidebar.selectbox('比較したい発刊月を選択', options=['すべて'] + available_months)


    df_filtered_by_month = df_filtered_by_date.copy()
    df_seisakubutsu_filtered_by_month = df_seisakubutsu_filtered_by_date.copy()

    if selected_year != 'すべて':
        df_filtered_by_month = df_filtered_by_month[df_filtered_by_month['年度'] == selected_year]
        df_seisakubutsu_filtered_by_month = df_seisakubutsu_filtered_by_month[df_seisakubutsu_filtered_by_month['年度'] == selected_year]

    if selected_month != 'すべて':
        df_filtered_by_month = df_filtered_by_month[df_filtered_by_month['発刊月'] == selected_month]
        df_seisakubutsu_filtered_by_month = df_seisakubutsu_filtered_by_month[df_seisakubutsu_filtered_by_month['発刊月'] == selected_month]

    # --- 学年フィルター ---
    st.sidebar.subheader("学年フィルター")
    grade_cols = [col for col in df_seisakubutsu_all.columns if '年生' in col or '学年その他' in col]
    melted_grades = df_seisakubutsu_filtered_by_month.melt(id_vars=['トークン'], value_vars=grade_cols, var_name='学年', value_name='対象')
    relevant_grades = melted_grades[melted_grades['対象'] == True]
    available_grades = relevant_grades['学年'].unique().tolist()
    selected_grades = st.sidebar.multiselect('分析したい学年を選択', options=available_grades, default=available_grades)

    if selected_grades:
        selected_tokens = relevant_grades[relevant_grades['学年'].isin(selected_grades)]['トークン'].unique()
        df_filtered = df_filtered_by_month[df_filtered_by_month['トークン'].isin(selected_tokens)].copy()
        df_seisakubutsu_filtered = df_seisakubutsu_filtered_by_month[df_seisakubutsu_filtered_by_month['トークン'].isin(selected_tokens)].copy()
    else:
        df_filtered = pd.DataFrame(columns=df_filtered_by_month.columns)
        df_seisakubutsu_filtered = pd.DataFrame(columns=df_seisakubutsu_filtered_by_month.columns)

    # --- 制作物名フィルター ---
    st.sidebar.subheader("制作物名フィルター")
    name_filter_text = st.sidebar.text_input('制作物名に含まれるテキストで絞り込み')
    if name_filter_text:
        df_filtered = df_filtered[df_filtered['制作物名'].str.contains(name_filter_text, na=False)].copy()
        df_seisakubutsu_filtered = df_seisakubutsu_filtered[df_seisakubutsu_filtered['制作物名'].str.contains(name_filter_text, na=False)].copy()

    # --- ダウンロード機能 ---
    st.sidebar.header("3. ダウンロード")
    if not df_filtered.empty:
        output = io.BytesIO()
        df_filtered.to_csv(output, index=False, encoding='shift_jis', errors='ignore')
        st.sidebar.text("フィルター後の統合CSVをダウンロード")
        st.sidebar.download_button(
            label="⬇️ ダウンロード", 
            data=output.getvalue(), 
            file_name='filtered_data.csv', 
            mime='text/csv'
        )


    # --- メインの表示エリア ---
    if df_filtered.empty:
        st.warning("選択された条件に該当するデータはありません。フィルター条件を変更してください。")
        st.stop()

    st.success(f"データ読み込み完了。現在 {len(df_seisakubutsu_filtered.drop_duplicates(subset=['トークン']))} 件の制作データを分析中です。")

    # --- タブに表示する工程を決定 ---
    processes_for_tabs = [p for p in original_process_order if p in df_filtered['工程'].unique()]

    # --- 工程別 統合分析ダッシュボード ---
    st.text("")
    st.header("📊 工程別 統合分析ダッシュボード")
    st.markdown("各工程のパフォーマンスと詳細分析を、以下のタブで切り替えて確認できます。")

    # --- タブ表示のためのデータ準備 ---
    # パフォーマンス分析用のデータを先に計算
    df_performance = pd.DataFrame() # Initialize empty
    if not df_filtered.empty and not relevant_grades.empty:
        # df_filtered に学年カラムを追加
        df_filtered_with_grade = pd.merge(df_filtered, relevant_grades[['トークン', '学年']].drop_duplicates(), on='トークン', how='left')
        df_seisakubutsu_filtered_with_grade = pd.merge(df_seisakubutsu_filtered, relevant_grades[['トークン', '学年']].drop_duplicates(), on='トークン', how='left')

        # 1. 分析対象の学年と工程のリストを作成
        active_processes = processes_for_tabs
        if selected_grades and active_processes:
            # 2. 骨格となるデータフレームを作成
            scaffold_mux = pd.MultiIndex.from_product([selected_grades, active_processes], names=['学年', '工程'])
            scaffold_df = pd.DataFrame(index=scaffold_mux).reset_index()

            # 3. 各指標を計算
            # 総工程数
            total_process_count_df = df_seisakubutsu_filtered_with_grade.groupby(['学年', '工程'], observed=True).size().rename('総工程数').reset_index()

            # 期限内完了率
            completed_checks_grouped = df_filtered_with_grade[df_filtered_with_grade['チェック済み'] == True].groupby(['学年', '工程'], observed=True).size().rename('completed_count')
            on_time_checks_grouped = df_filtered_with_grade[(df_filtered_with_grade['チェック済み'] == True) & (df_filtered_with_grade['修正日_header'] <= df_filtered_with_grade['締め切り日'])].groupby(['学年', '工程'], observed=True).size().rename('on_time_count')
            on_time_rate_df = pd.concat([completed_checks_grouped, on_time_checks_grouped], axis=1).reset_index()
            if 'completed_count' in on_time_rate_df.columns:
                on_time_rate_df['期限内完了率(%)'] = (on_time_rate_df['on_time_count'] / on_time_rate_df['completed_count']) * 100
            else:
                on_time_rate_df['期限内完了率(%)'] = 0
            on_time_rate_df.replace([float('inf'), -float('inf')], 0, inplace=True)
            on_time_rate_df['期限内完了率(%)'] = on_time_rate_df['期限内完了率(%)'].fillna(0)

            # 平均チェック者数 (制作物ごと(トークン)にユニーク化した上で平均を計算)
            avg_checkers_base = df_filtered_with_grade[['学年', '工程', 'トークン', 'チェック者数']].drop_duplicates()
            avg_checkers_df = avg_checkers_base.groupby(['学年', '工程'], observed=True)['チェック者数'].mean().rename('平均チェック者数(人)').reset_index()

            # 4. 骨格にマージ
            df_performance = pd.merge(scaffold_df, total_process_count_df, on=['学年', '工程'], how='left')
            df_performance = pd.merge(df_performance, on_time_rate_df[['学年', '工程', '期限内完了率(%)']], on=['学年', '工程'], how='left')
            df_performance = pd.merge(df_performance, avg_checkers_df, on=['学年', '工程'], how='left')

            # 5. クリーンアップ
            numeric_cols = ['総工程数', '期限内完了率(%)', '平均チェック者数(人)']
            for col in numeric_cols:
                if col in df_performance.columns:
                    df_performance[col] = df_performance[col].fillna(0)
            
            if '総工程数' in df_performance.columns:
                df_performance['総工程数'] = df_performance['総工程数'].astype(int)

            df_performance = df_performance.round(1)
            
            # 表示用にソート
            df_performance['学年'] = pd.Categorical(df_performance['学年'], categories=selected_grades, ordered=True)
            df_performance['工程'] = pd.Categorical(df_performance['工程'], categories=active_processes, ordered=True)
            df_performance = df_performance.sort_values(by=['学年', '工程'])

    # --- 統合タブの作成 ---
    if processes_for_tabs:
        process_tabs = st.tabs(processes_for_tabs)

        for i, process_name in enumerate(processes_for_tabs):
            with process_tabs[i]:
                # フィルターされたデータから、現在のタブの工程のデータを抽出
                df_process_detail_filtered = df_filtered[df_filtered['工程'] == process_name].copy()
                df_seisakubutsu_process_detail_filtered = df_seisakubutsu_filtered[df_seisakubutsu_filtered['工程'] == process_name].copy()

                if df_process_detail_filtered.empty:
                    st.info(f"この工程に関するデータはありません。")
                    continue

                # --- Part 1: パフォーマンス分析 ---
                st.subheader(f"パフォーマンス・ベンチマーキング")
                if not df_performance.empty:
                    df_performance_tab = df_performance[df_performance['工程'] == process_name].copy()
                    if not df_performance_tab.empty:
                        st.dataframe(df_performance_tab[['学年', '総工程数', '期限内完了率(%)', '平均チェック者数(人)']], use_container_width=True)
                    else:
                        st.info(f"{process_name} のパフォーマンスデータがありません。")
                else:
                    st.info("パフォーマンスデータを計算できませんでした。")
                
                

                st.markdown("---")

                # --- Part 2: 詳細分析 ---
                st.subheader(f"詳細分析")

                # --- 工程・品質分析 --- 
                rework_definitions = [p for p in original_process_order if
                                    ('再校' in p or '念校' in p or '色校' in p or 'α' in p or 'β' in p) and 
                                    p in df_seisakubutsu_process_detail_filtered['工程'].unique()]
                df_seisakubutsu_process_detail_filtered['手戻り'] = df_seisakubutsu_process_detail_filtered['工程'].isin(rework_definitions)
                
                # 学年・工程別の次回チェック出し状況
                st.markdown("**学年別の『次回チェック出し』状況**")
                
                melted_grades_current_process = df_seisakubutsu_process_detail_filtered.melt(id_vars=['トークン'], value_vars=grade_cols, var_name='学年', value_name='対象')
                relevant_grades_current_process = melted_grades_current_process[melted_grades_current_process['対象'] == True]

                df_next_check_base = pd.merge(df_process_detail_filtered, relevant_grades_current_process[['トークン', '学年']].drop_duplicates(), on='トークン', how='left')

                scaffold_grades_df = pd.DataFrame({'学年': selected_grades})

                if not df_next_check_base.empty and '学年' in df_next_check_base.columns:
                    grouped = df_next_check_base.groupby(['学年'], observed=True)['次回チェック出し']
                    count = grouped.sum().astype(int).rename('次回チェック出し要_人数')
                    total_in_group = grouped.size()
                    ratio = (count / total_in_group * 100).round(1).rename('次回チェック出し要_割合(%)')
                    calculated_df = pd.concat([count, ratio], axis=1).reset_index()
                else:
                    calculated_df = pd.DataFrame(columns=['学年', '次回チェック出し要_人数', '次回チェック出し要_割合(%)'])

                result_df = pd.merge(scaffold_grades_df, calculated_df, on='学年', how='left')
                result_df[['次回チェック出し要_人数', '次回チェック出し要_割合(%)']] = result_df[['次回チェック出し要_人数', '次回チェック出し要_割合(%)']].fillna(0)
                result_df['次回チェック出し要_人数'] = result_df['次回チェック出し要_人数'].astype(int)
                result_df['学年'] = pd.Categorical(result_df['学年'], categories=selected_grades, ordered=True)
                result_df = result_df.sort_values(by='学年')

                if not result_df.empty:
                    fig_ratio = px.bar(result_df, x='学年', y='次回チェック出し要_割合(%)', title='学年別「次回チェック出し要」の割合', text_auto='.1f', color='学年')
                    fig_ratio.update_layout(showlegend=False, xaxis_title=None)
                    st.plotly_chart(fig_ratio, use_container_width=True, key=f"ratio_chart_{process_name}")
                    
                    fig_count = px.bar(result_df, x='学年', y='次回チェック出し要_人数', title='学年別「次回チェック出し要」の人数', text_auto=True, color='学年')
                    fig_count.update_layout(showlegend=False, xaxis_title=None)
                    st.plotly_chart(fig_count, use_container_width=True, key=f"count_chart_{process_name}")
                else:
                    st.info(f"「次回チェック出し」のデータがありません。")
    else:
        st.info("選択された条件に該当する工程データがありません。")

    # --- ROI分析セクション（最下部へ移動） ---
    st.header("ROI（費用対効果）分析")
    with st.expander("総短縮時間の試算"):
        total_requests = len(df_seisakubutsu_filtered['トークン'].unique())
        time_saved_per_request = 5  # 1件あたりの短縮時間（分）
        total_minutes_saved = total_requests * time_saved_per_request
        hours_saved = total_minutes_saved // 60
        minutes_saved = total_minutes_saved % 60

        st.metric(
            label=f"期間内の総チェック出し案件数",
            value=f"{total_requests} 件",
            delta=f"約 {hours_saved} 時間 {minutes_saved} 分の短縮効果が見込まれます",
            delta_color="off"
        )
        st.info(f"この試算は、1案件あたり {time_saved_per_request} 分の時間が短縮されると仮定した場合のものです。")

else:
    st.info("サイドバーから分析対象のCSVファイルを2つアップロードすると、分析が始まります。")
