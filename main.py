# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import plotly.express as px
import io
import gc
from datetime import datetime

# =========================
# 安全運用メモ
# - キャッシュ未使用（@st.cache_data削除）
# - PII(担当者メールアドレス)は集計後に即drop
# - 例外は簡素化して詳細は出さない
# - ダウンロードはUTF-8-SIG（文字化け&欠落回避）
# - ログ(st.write/print)に生データを出さない
# =========================

month_order = ['4月号', '5月号', '6月号', '7月号', '8月号', '9月号', '10月号', '11月号', '12月号', '1月号', '2月号', '3月号', 'その他']

# 工程の順序（重複除去済）
original_process_order = list(dict.fromkeys([
    '仮台割', '入稿前ラフ', '入稿原稿', '組版原稿', '初校', '再校', '再校2', '再校3',
    '色校', '色校2', '色校3', '念校', '念校2', '念校3', 'α1版', 'β1版', 'β2版',
    'β3版', 'β4版', 'β5版', 'その他'
]))

# --- Streamlit ページ設定 ---
st.set_page_config(page_title="社内チェック業務 BPR分析ツール", layout="wide")
st.title("📊 社内チェック業務 BPR分析ツール")

# --- ファイルアップローダー ---
st.sidebar.header("1. ファイルアップロード")
st.sidebar.info("分析対象のCSVファイルを2つアップロードしてください。")
uploaded_seisakubutsu_file = st.sidebar.file_uploader("制作物一覧 CSV", type="csv")
uploaded_header_file = st.sidebar.file_uploader("ヘッダー一覧 CSV", type="csv")

# --- データ読み込み（非キャッシュ） ---
def load_data(seisakubutsu_file, header_file):
    """アップロードCSVを読み込み、結合・前処理を行う（PIIは早期除去）"""
    try:
        seisakubutsu_df = pd.read_csv(seisakubutsu_file)
        header_df = pd.read_csv(header_file)
    except Exception:
        st.error("エラー: ファイルの読み込みに失敗しました。CSV形式や文字コードをご確認ください。")
        return None, None

    # 日付列の正規化（tz無し）
    date_cols = ['作成日', '修正日', '締め切り日']
    for col in date_cols:
        if col in seisakubutsu_df.columns:
            seisakubutsu_df[col] = pd.to_datetime(seisakubutsu_df[col], errors='coerce').dt.tz_localize(None)
        if col in header_df.columns:
            header_df[col] = pd.to_datetime(header_df[col], errors='coerce').dt.tz_localize(None)

    # 列名整形 & チェック者数集計
    header_df.rename(columns={'制作物トークン': 'トークン'}, inplace=True)
    if '担当者メールアドレス' in header_df.columns:
        checkers_count_df = header_df.groupby('トークン')['担当者メールアドレス'].nunique().reset_index()
        checkers_count_df.rename(columns={'担当者メールアドレス': 'チェック者数'}, inplace=True)
        # PIIは以降不要なので速やかに削除
        header_df = header_df.drop(columns=['担当者メールアドレス'])
    else:
        checkers_count_df = pd.DataFrame(columns=['トークン', 'チェック者数'])

    # 制作物側へチェック者数を付与
    seisakubutsu_df = pd.merge(seisakubutsu_df, checkers_count_df, on='トークン', how='left')
    seisakubutsu_df['チェック者数'] = seisakubutsu_df['チェック者数'].fillna(0)

    # ヘッダーと制作物を結合
    merged_df = pd.merge(header_df, seisakubutsu_df, on='トークン', suffixes=('_header', '_seisakubutsu'))

    # 発刊月のカテゴリ順序
    for df in (merged_df, seisakubutsu_df):
        if '発刊月' in df.columns:
            df['発刊月'] = pd.Categorical(df['発刊月'], categories=month_order, ordered=True)

    # 実データに存在する工程のみ許容
    existing_processes = pd.concat([
        merged_df['工程'] if '工程' in merged_df.columns else pd.Series(dtype=str),
        seisakubutsu_df['工程'] if '工程' in seisakubutsu_df.columns else pd.Series(dtype=str)
    ]).dropna().unique()
    filtered_process_order = [p for p in original_process_order if p in existing_processes]
    for df in (merged_df, seisakubutsu_df):
        if '工程' in df.columns:
            df['工程'] = pd.Categorical(df['工程'], categories=filtered_process_order, ordered=True)

    return merged_df, seisakubutsu_df

# --- メイン処理 ---
if uploaded_seisakubutsu_file is not None and uploaded_header_file is not None:
    df_merged_all, df_seisakubutsu_all = load_data(uploaded_seisakubutsu_file, uploaded_header_file)
    if df_merged_all is None:
        st.stop()

    st.sidebar.header("2. 絞り込みフィルター")
    # 期間フィルター
    if '作成日' not in df_seisakubutsu_all.columns or df_seisakubutsu_all['作成日'].dropna().empty:
        st.error("エラー: 制作物CSVに『作成日』列がありません（または全て欠損）")
        st.stop()

    min_date = df_seisakubutsu_all['作成日'].min().date()
    max_date = df_seisakubutsu_all['作成日'].max().date()
    start_date = st.sidebar.date_input('開始日', min_date, min_value=min_date, max_value=max_date)
    end_date = st.sidebar.date_input('終了日', max_date, min_value=start_date, max_value=max_date)

    if start_date > end_date:
        st.sidebar.error('エラー: 終了日は開始日以降に設定してください。')
        st.stop()

    start_datetime = pd.to_datetime(start_date)
    end_datetime = pd.to_datetime(end_date) + pd.Timedelta(days=1)

    # 期間適用（結合側は作成日_seisakubutsu）
    df_filtered_by_date = df_merged_all[
        (df_merged_all['作成日_seisakubutsu'] >= start_datetime) &
        (df_merged_all['作成日_seisakubutsu'] < end_datetime)
    ].copy()
    df_seisakubutsu_filtered_by_date = df_seisakubutsu_all[
        (df_seisakubutsu_all['作成日'] >= start_datetime) &
        (df_seisakubutsu_all['作成日'] < end_datetime)
    ].copy()

    # 発刊年度フィルター
    st.sidebar.subheader("発刊年度フィルター")
    available_years = sorted(df_seisakubutsu_filtered_by_date['年度'].dropna().unique().tolist()) \
        if '年度' in df_seisakubutsu_filtered_by_date.columns else []
    selected_year = st.sidebar.selectbox('比較したい発刊年度を選択', options=['すべて'] + available_years)

    # 発刊月フィルター
    st.sidebar.subheader("発刊月フィルター")
    if '発刊月' in df_seisakubutsu_filtered_by_date.columns:
        available_months = [m for m in month_order if m in df_seisakubutsu_filtered_by_date['発刊月'].dropna().unique()]
    else:
        available_months = []
    selected_month = st.sidebar.selectbox('比較したい発刊月を選択', options=['すべて'] + available_months)

    df_filtered_by_month = df_filtered_by_date.copy()
    df_seisakubutsu_filtered_by_month = df_seisakubutsu_filtered_by_date.copy()
    if selected_year != 'すべて' and '年度' in df_filtered_by_month.columns:
        df_filtered_by_month = df_filtered_by_month[df_filtered_by_month['年度'] == selected_year]
        df_seisakubutsu_filtered_by_month = df_seisakubutsu_filtered_by_month[df_seisakubutsu_filtered_by_month['年度'] == selected_year]
    if selected_month != 'すべて' and '発刊月' in df_filtered_by_month.columns:
        df_filtered_by_month = df_filtered_by_month[df_filtered_by_month['発刊月'] == selected_month]
        df_seisakubutsu_filtered_by_month = df_seisakubutsu_filtered_by_month[df_seisakubutsu_filtered_by_month['発刊月'] == selected_month]

    # 学年フィルター
    st.sidebar.subheader("学年フィルター")
    grade_cols = [c for c in df_seisakubutsu_all.columns if ('年生' in c or '学年その他' in c)]
    melted_grades = df_seisakubutsu_filtered_by_month.melt(
        id_vars=['トークン'], value_vars=grade_cols, var_name='学年', value_name='対象'
    ) if grade_cols else pd.DataFrame(columns=['トークン', '学年', '対象'])

    relevant_grades = melted_grades[melted_grades['対象'] == True] if not melted_grades.empty else pd.DataFrame(columns=['トークン','学年'])
    available_grades = relevant_grades['学年'].unique().tolist() if not relevant_grades.empty else []
    selected_grades = st.sidebar.multiselect('分析したい学年を選択', options=available_grades, default=available_grades)

    if selected_grades and not relevant_grades.empty:
        selected_tokens = relevant_grades[relevant_grades['学年'].isin(selected_grades)]['トークン'].unique()
        df_filtered = df_filtered_by_month[df_filtered_by_month['トークン'].isin(selected_tokens)].copy()
        df_seisakubutsu_filtered = df_seisakubutsu_filtered_by_month[df_seisakubutsu_filtered_by_month['トークン'].isin(selected_tokens)].copy()
    else:
        df_filtered = pd.DataFrame(columns=df_filtered_by_month.columns)
        df_seisakubutsu_filtered = pd.DataFrame(columns=df_seisakubutsu_filtered_by_month.columns)

    # 制作物名フィルター
    st.sidebar.subheader("制作物名フィルター")
    name_filter_text = st.sidebar.text_input('制作物名に含まれるテキストで絞り込み')
    if name_filter_text and '制作物名' in df_filtered.columns:
        df_filtered = df_filtered[df_filtered['制作物名'].str.contains(name_filter_text, na=False)].copy()
        df_seisakubutsu_filtered = df_seisakubutsu_filtered[df_seisakubutsu_filtered['制作物名'].str.contains(name_filter_text, na=False)].copy()

    # ダウンロード
    st.sidebar.header("3. ダウンロード")
    if not df_filtered.empty:
        output = io.BytesIO()
        # 文字欠落を避けるため UTF-8-SIG を使用（Excel互換）
        df_filtered.to_csv(output, index=False, encoding='utf-8-sig')
        st.sidebar.text("フィルター後の統合CSVをダウンロード")
        st.sidebar.download_button(
            label="⬇️ ダウンロード",
            data=output.getvalue(),
            file_name='filtered_data.csv',
            mime='text/csv'
        )
        del output

    # 表示ガード
    if df_filtered.empty:
        st.warning("選択された条件に該当するデータはありません。フィルター条件を変更してください。")
        st.stop()

    # サマリー
    unique_items = df_seisakubutsu_filtered['制作物名'].nunique() if '制作物名' in df_seisakubutsu_filtered.columns else 0
    st.success(f"データ読み込み完了。現在 {unique_items} 件の制作物データを分析中です。")

    processes_for_tabs = [p for p in original_process_order if '工程' in df_filtered.columns and p in df_filtered['工程'].unique()]

    # --- 全体サマリー ---
    st.text("")
    st.header("📊 全体サマリー")
    st.markdown("フィルターで絞り込んだデータ全体の概要（学年別・合計）と、発刊月ごとの推移を確認できます。")

    # 学年別サマリー
    if not relevant_grades.empty:
        df_filtered_with_grade_summary = pd.merge(
            df_filtered, relevant_grades[['トークン', '学年']].drop_duplicates(), on='トークン', how='left'
        )
        df_seisakubutsu_with_grade_summary = pd.merge(
            df_seisakubutsu_filtered, relevant_grades[['トークン', '学年']].drop_duplicates(), on='トークン', how='left'
        )

        summary_items = df_seisakubutsu_with_grade_summary.groupby('学年', observed=True)['制作物名'].nunique().rename('総制作物件数')
        summary_processes = df_seisakubutsu_with_grade_summary.groupby('学年', observed=True).size().rename('総工程数')

        completed_checks = df_filtered_with_grade_summary[df_filtered_with_grade_summary.get('チェック済み', False) == True] \
            .groupby('学年', observed=True).size().rename('completed')
        on_time_checks = df_filtered_with_grade_summary[
            (df_filtered_with_grade_summary.get('チェック済み', False) == True) &
            (df_filtered_with_grade_summary.get('修正日_header') <= df_filtered_with_grade_summary.get('締め切り日'))
        ].groupby('学年', observed=True).size().rename('on_time')

        on_time_summary = pd.concat([completed_checks, on_time_checks], axis=1).fillna(0)
        on_time_summary['期限内完了率(%)'] = (
            on_time_summary['on_time'] / on_time_summary['completed'] * 100
        ).where(on_time_summary['completed'] > 0, 0)

        avg_checkers = df_seisakubutsu_with_grade_summary.drop_duplicates(subset=['学年', 'トークン']) \
            .groupby('学年', observed=True)['チェック者数'].mean().rename('平均チェック者数(人)')

        summary_by_grade_df = pd.concat(
            [summary_items, summary_processes, on_time_summary['期限内完了率(%)'], avg_checkers], axis=1
        ).reset_index().fillna(0)

        # 全体合計
        total_items = df_seisakubutsu_filtered['制作物名'].nunique() if '制作物名' in df_seisakubutsu_filtered.columns else 0
        total_processes = len(df_seisakubutsu_filtered)
        total_completed = int(df_filtered.get('チェック済み', pd.Series(dtype=bool)).sum()) if 'チェック済み' in df_filtered.columns else 0
        total_on_time = df_filtered[
            (df_filtered.get('チェック済み', False) == True) &
            (df_filtered.get('修正日_header') <= df_filtered.get('締め切り日'))
        ].shape[0] if {'修正日_header','締め切り日','チェック済み'}.issubset(df_filtered.columns) else 0
        total_on_time_rate = (total_on_time / total_completed * 100) if total_completed > 0 else 0
        total_avg_checkers = df_seisakubutsu_filtered.drop_duplicates(subset=['トークン'])['チェック者数'].mean() \
            if 'チェック者数' in df_seisakubutsu_filtered.columns else 0

        total_summary_df = pd.DataFrame([{
            '学年': '合計',
            '総制作物件数': total_items,
            '総工程数': total_processes,
            '期限内完了率(%)': total_on_time_rate,
            '平均チェック者数(人)': total_avg_checkers
        }])

        final_summary_df = pd.concat([summary_by_grade_df, total_summary_df], ignore_index=True).fillna(0)
        for col in ['総制作物件数', '総工程数']:
            if col in final_summary_df.columns:
                final_summary_df[col] = final_summary_df[col].astype(int)
        final_summary_df = final_summary_df.round(1)

        st.subheader("学年別サマリー")
        show_cols = ['学年', '総制作物件数', '総工程数', '期限内完了率(%)', '平均チェック者数(人)']
        st.dataframe(final_summary_df[[c for c in show_cols if c in final_summary_df.columns]], use_container_width=True)
    else:
        st.info("学年データがないため、学年別サマリーは表示できません。")

    st.markdown("---")

    # 発刊月の推移
    st.subheader("発刊月ごとの推移")
    if not relevant_grades.empty and '発刊月' in df_seisakubutsu_filtered.columns:
        monthly_by_grade = df_seisakubutsu_with_grade_summary.groupby(['発刊月', '学年'], observed=True).agg(
            制作物件数=('制作物名', 'nunique'),
            総工程数=('トークン', 'size')
        ).reset_index()

        monthly_total = df_seisakubutsu_filtered.groupby('発刊月', observed=True).agg(
            制作物件数=('制作物名', 'nunique'),
            総工程数=('トークン', 'size')
        ).reset_index()
        monthly_total['学年'] = '合計'

        monthly_summary = pd.concat([monthly_by_grade, monthly_total], ignore_index=True)
        monthly_summary['発刊月'] = pd.Categorical(monthly_summary['発刊月'], categories=month_order, ordered=True)
        monthly_summary_for_graph = monthly_summary[monthly_summary['発刊月'] != 'その他'].copy().sort_values('発刊月')

        if not monthly_summary_for_graph.empty:
            col1, col2 = st.columns(2)
            with col1:
                fig_a = px.line(monthly_summary_for_graph, x='発刊月', y='制作物件数', color='学年',
                                title='発刊月ごとの制作物件数', markers=True,
                                color_discrete_sequence=px.colors.qualitative.T10)
                fig_a.update_layout(xaxis_title=None, legend_title_text='学年')
                fig_a.update_xaxes(categoryorder='array', categoryarray=[m for m in month_order if m != 'その他'])
                st.plotly_chart(fig_a, use_container_width=True)
            with col2:
                fig_b = px.line(monthly_summary_for_graph, x='発刊月', y='総工程数', color='学年',
                                title='発刊月ごとの総工程数', markers=True,
                                color_discrete_sequence=px.colors.qualitative.T10)
                fig_b.update_layout(xaxis_title=None, legend_title_text='学年')
                fig_b.update_xaxes(categoryorder='array', categoryarray=[m for m in month_order if m != 'その他'])
                st.plotly_chart(fig_b, use_container_width=True)
        else:
            st.info("発刊月ごとの集計データがありません。")
    else:
        st.info("学年データがないため、発刊月ごとの推移は表示できません。")

    # --- 工程別 統合分析 ---
    st.text("")
    st.header("📊 工程別 統合分析ダッシュボード")
    st.markdown("各工程のパフォーマンスと詳細分析を、以下のタブで切り替えて確認できます。")

    df_performance = pd.DataFrame()
    if not df_filtered.empty and not relevant_grades.empty and '工程' in df_filtered.columns:
        df_filtered_with_grade = pd.merge(
            df_filtered, relevant_grades[['トークン', '学年']].drop_duplicates(), on='トークン', how='left'
        )
        df_seisakubutsu_with_grade = pd.merge(
            df_seisakubutsu_filtered, relevant_grades[['トークン', '学年']].drop_duplicates(), on='トークン', how='left'
        )

        active_processes = processes_for_tabs
        if selected_grades and active_processes:
            scaffold_df = pd.MultiIndex.from_product([selected_grades, active_processes], names=['学年', '工程']).to_frame(index=False)

            total_process_count_df = df_seisakubutsu_with_grade.groupby(['学年', '工程'], observed=True).size() \
                .rename('総工程数').reset_index()

            completed_g = df_filtered_with_grade[df_filtered_with_grade.get('チェック済み', False) == True] \
                .groupby(['学年', '工程'], observed=True).size().rename('completed_count')
            ontime_g = df_filtered_with_grade[
                (df_filtered_with_grade.get('チェック済み', False) == True) &
                (df_filtered_with_grade.get('修正日_header') <= df_filtered_with_grade.get('締め切り日'))
            ].groupby(['学年', '工程'], observed=True).size().rename('on_time_count')

            on_time_rate_df = pd.concat([completed_g, ontime_g], axis=1).reset_index().fillna(0)
            on_time_rate_df['期限内完了率(%)'] = (
                on_time_rate_df['on_time_count'] / on_time_rate_df['completed_count']
            ).replace([float('inf'), -float('inf')], 0).fillna(0) * 100

            avg_checkers_df = df_filtered_with_grade[['学年', '工程', 'トークン', 'チェック者数']] \
                .drop_duplicates().groupby(['学年', '工程'], observed=True)['チェック者数'] \
                .mean().rename('平均チェック者数(人)').reset_index()

            df_performance = scaffold_df.merge(total_process_count_df, on=['学年', '工程'], how='left') \
                                        .merge(on_time_rate_df[['学年', '工程', '期限内完了率(%)']], on=['学年', '工程'], how='left') \
                                        .merge(avg_checkers_df, on=['学年', '工程'], how='left') \
                                        .fillna(0)

            if '総工程数' in df_performance.columns:
                df_performance['総工程数'] = df_performance['総工程数'].astype(int)
            df_performance = df_performance.round(1)
            df_performance['学年'] = pd.Categorical(df_performance['学年'], categories=selected_grades, ordered=True)
            df_performance['工程'] = pd.Categorical(df_performance['工程'], categories=active_processes, ordered=True)
            df_performance = df_performance.sort_values(by=['学年', '工程'])

    if processes_for_tabs:
        process_tabs = st.tabs(processes_for_tabs)
        for i, process_name in enumerate(processes_for_tabs):
            with process_tabs[i]:
                df_proc = df_filtered[df_filtered.get('工程') == process_name].copy()
                df_proc_sei = df_seisakubutsu_filtered[df_seisakubutsu_filtered.get('工程') == process_name].copy()

                if df_proc.empty:
                    st.info("この工程に関するデータはありません。")
                    continue

                st.subheader("パフォーマンス・ベンチマーキング")
                if not df_performance.empty:
                    view = df_performance[df_performance['工程'] == process_name]
                    if not view.empty:
                        st.dataframe(view[['学年', '総工程数', '期限内完了率(%)', '平均チェック者数(人)']], use_container_width=True)
                    else:
                        st.info(f"{process_name} のパフォーマンスデータがありません。")
                else:
                    st.info("パフォーマンスデータを計算できませんでした。")

                st.markdown("---")
                st.subheader("詳細分析")

                # 手戻り判定
                rework_defs = [p for p in original_process_order if
                               ('再校' in p or '念校' in p or '色校' in p or 'α' in p or 'β' in p)]
                if '工程' in df_proc_sei.columns:
                    df_proc_sei['手戻り'] = df_proc_sei['工程'].isin(rework_defs)

                st.markdown("**学年別の『次回チェック出し』状況**")
                if grade_cols:
                    melted_cur = df_proc_sei.melt(id_vars=['トークン'], value_vars=grade_cols,
                                                  var_name='学年', value_name='対象') if not df_proc_sei.empty else pd.DataFrame(columns=['トークン','学年','対象'])
                    rel_cur = melted_cur[melted_cur['対象'] == True] if not melted_cur.empty else pd.DataFrame(columns=['トークン','学年'])

                    df_next = pd.merge(df_proc, rel_cur[['トークン', '学年']].drop_duplicates(), on='トークン', how='left') \
                        if not df_proc.empty else pd.DataFrame(columns=['学年','次回チェック出し'])

                    scaffold_grades_df = pd.DataFrame({'学年': selected_grades})
                    if not df_next.empty and '学年' in df_next.columns and '次回チェック出し' in df_next.columns:
                        grouped = df_next.groupby(['学年'], observed=True)['次回チェック出し']
                        count = grouped.sum().astype(int).rename('次回チェック出し要_人数')
                        total_in_group = grouped.size()
                        ratio = (count / total_in_group * 100).round(1).rename('次回チェック出し要_割合(%)')
                        calc_df = pd.concat([count, ratio], axis=1).reset_index()
                    else:
                        calc_df = pd.DataFrame(columns=['学年', '次回チェック出し要_人数', '次回チェック出し要_割合(%)'])

                    result_df = pd.merge(scaffold_grades_df, calc_df, on='学年', how='left').fillna(0)
                    result_df['次回チェック出し要_人数'] = result_df['次回チェック出し要_人数'].astype(int)
                    result_df['学年'] = pd.Categorical(result_df['学年'], categories=selected_grades, ordered=True)
                    result_df = result_df.sort_values(by='学年')

                    if not result_df.empty:
                        fig_ratio = px.bar(result_df, x='学年', y='次回チェック出し要_割合(%)',
                                           title='学年別「次回チェック出し要」の割合', text_auto='.1f', color='学年')
                        fig_ratio.update_layout(showlegend=False, xaxis_title=None)
                        st.plotly_chart(fig_ratio, use_container_width=True, key=f"ratio_chart_{process_name}")

                        fig_count = px.bar(result_df, x='学年', y='次回チェック出し要_人数',
                                           title='学年別「次回チェック出し要」の人数', text_auto=True, color='学年')
                        fig_count.update_layout(showlegend=False, xaxis_title=None)
                        st.plotly_chart(fig_count, use_container_width=True, key=f"count_chart_{process_name}")
                    else:
                        st.info("「次回チェック出し」のデータがありません。")
                else:
                    st.info("学年列が存在しないため、次回チェック出し状況は表示できません。")
    else:
        st.info("選択された条件に該当する工程データがありません。")

    # 後処理（大きなDFを解放）
    del df_merged_all, df_seisakubutsu_all
    del df_filtered_by_date, df_seisakubutsu_filtered_by_date
    del df_filtered_by_month, df_seisakubutsu_filtered_by_month
    del df_filtered, df_seisakubutsu_filtered
    gc.collect()

else:
    st.info("サイドバーから分析対象のCSVファイルを2つアップロードすると、分析が始まります。")
